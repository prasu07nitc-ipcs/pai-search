"""Scoped Git commits and pushes for the common transaction runner."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

SCOPE = ("data/articles", "data/index", "data/queries")
CONFIG = Path(__file__).with_name("git-config.json")
PROJECT = CONFIG.resolve().parents[2]
PREFIXES = tuple(os.fsencode(directory + "/") for directory in SCOPE)
OPERATION_MARKERS = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
    "rebase-apply", "sequencer",
)


def git(*args, input_bytes=None):
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", *args],
        env=environment,
        input=input_bytes,
        stdin=subprocess.DEVNULL if input_bytes is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=60,
    )
    return result.stdout


def line(*args):
    return os.fsdecode(git(*args)).rstrip("\n")


def check_paths(paths):
    for path in paths:
        if path and not path.startswith(PREFIXES):
            raise ValueError(f"Path outside commit scope: {os.fsdecode(path)!r}")


def check_worktree():
    entries = git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all",
        "--no-renames", "--ignore-submodules=none",
    ).split(b"\0")
    check_paths(entry[3:] for entry in entries if entry)


def check_history(head, bases):
    exclusions = ["--not", *bases] if bases else []
    commits = git("rev-list", head, *exclusions)
    if commits:
        paths = git(
            "diff-tree", "--stdin", "--root", "-m", "-r", "--no-commit-id",
            "--name-only", "--no-renames", "-z", input_bytes=commits,
        )
        check_paths(paths.split(b"\0"))


def committed_page_ids(parent, commit):
    paths = git(
        "diff-tree", "-r", "--no-commit-id", "--name-only", "--no-renames",
        "--diff-filter=AM", "-z", parent, commit, "--", *SCOPE[:2],
    )
    return sorted({
        os.fsdecode(match[1])
        for path in paths.split(b"\0")
        if (match := re.fullmatch(
            rb"data/(?:articles/[^/]+|index/[^/]+/[^/]+)/([0-9a-f]{64})\.md", path
        ))
    })


def validate_input(value):
    if not isinstance(value, dict) or value.keys() != {"file_paths", "commit_message"}:
        raise ValueError('Supply an object with "file_paths" and "commit_message".')
    message = value["commit_message"]
    if not isinstance(message, str) or not message.strip() or "\0" in message:
        raise ValueError("commit_message must be a nonblank string without NUL characters.")
    message.encode("utf-8")
    paths = value["file_paths"]
    if not isinstance(paths, list) or not paths:
        raise ValueError("file_paths must be a nonempty list.")
    for path in paths:
        if (
            not isinstance(path, str) or "\0" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError(f"Expected a repository-relative file path: {path!r}")
        check_paths([os.fsencode(path)])
    if len(paths) != len(set(paths)):
        raise ValueError("file_paths must not contain duplicates.")
    return paths, message


def check_selected_files(paths):
    for name in paths:
        path = Path(name)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError(f"Symlinked file path: {name!r}")
        if path.is_file():
            continue
        tracked = git("--literal-pathspecs", "ls-files", "-z", "--", name).split(b"\0")
        if path.exists() or os.fsencode(name) not in tracked:
            raise ValueError(f"Expected a file or a tracked deletion: {name!r}")


def run(result, paths, message):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    author, email = (config[key] for key in ("author", "email"))
    for value in (author, email):
        if not isinstance(value, str) or not value.strip() or any(
            character in value for character in "\r\n\0<>"
        ):
            raise ValueError("Invalid Git identity in git-config.json.")

    if Path(line("rev-parse", "--show-toplevel")).resolve() != Path.cwd():
        raise ValueError("Run from the root of the target repository.")
    if line("rev-parse", "--is-shallow-repository") == "true":
        raise ValueError("A full checkout is required to validate outgoing history.")
    branch_ref = line("symbolic-ref", "HEAD")
    branch = branch_ref.removeprefix("refs/heads/")
    head = line("rev-parse", "--verify", "HEAD")
    marker_args = [arg for marker in OPERATION_MARKERS for arg in ("--git-path", marker)]
    if any(Path(path).exists() for path in line("rev-parse", *marker_args).splitlines()):
        raise ValueError("Finish the in-progress Git operation first.")
    check_worktree()
    check_selected_files(paths)

    remotes = line("remote").splitlines()
    if not remotes:
        raise ValueError("The repository has no configured remote.")
    configured_remote = line(
        "for-each-ref", "--format=%(upstream:remotename)", branch_ref
    )
    if configured_remote in remotes:
        remote = configured_remote
    elif "origin" in remotes:
        remote = "origin"
    elif len(remotes) == 1:
        remote = remotes[0]
    else:
        raise ValueError("Configure a branch remote or an origin remote.")
    push_urls = line("remote", "get-url", "--push", "--all", remote).splitlines()
    if len(push_urls) != 1:
        raise ValueError("The selected remote must have one push URL.")
    destination = push_urls[0]

    # Fetch from the actual push destination, including when pushurl differs.
    advertised = line("ls-remote", "--heads", "--", destination)
    heads = {ref: oid for oid, ref in (
        entry.split("\t", 1) for entry in advertised.splitlines()
    )}
    tip = heads.get(branch_ref, "")
    bases = [tip] if tip else sorted(set(heads.values()))
    if bases and head != tip:
        objects = git(
            "cat-file", "--batch-check=%(objectname) %(objecttype)",
            input_bytes=("\n".join(bases) + "\n").encode("ascii"),
        )
        missing = [
            oid for oid, info in zip(bases, objects.splitlines(), strict=True)
            if not info.endswith(b" commit")
        ]
        if missing:
            git(
                "fetch", "--no-tags", "--no-recurse-submodules",
                "--no-write-fetch-head", "--", destination, *missing,
            )
    if tip and head != tip:
        try:
            git("merge-base", "--is-ancestor", tip, head)
        except subprocess.CalledProcessError as error:
            if error.returncode == 1:
                raise ValueError("The remote branch has commits missing locally.") from error
            raise
    if head != tip:
        check_history(head, bases)

    if line("symbolic-ref", "HEAD") != branch_ref or line("rev-parse", "HEAD") != head:
        raise ValueError("The checkout changed during validation.")
    check_worktree()
    check_selected_files(paths)
    git("--literal-pathspecs", "add", "-f", "-A", "--", *paths)
    staged = git("--literal-pathspecs", "diff", "--cached", "--name-only",
                 "--no-renames", "-z", "--", *paths)
    if staged:
        git(
            "--literal-pathspecs", "-c", f"user.name={author}", "-c", f"user.email={email}",
            "-c", "commit.gpgSign=false", "commit", "--only", "--author",
            f"{author} <{email}>", "--cleanup=verbatim", "-m", message, "--", *paths,
        )
        commit = line("rev-parse", branch_ref)
        result["commit"] = commit
        if line("rev-list", "--parents", "-n", "1", commit).split() != [commit, head]:
            raise ValueError("The new commit does not have the expected parent.")
        changed = git("diff-tree", "-r", "--no-commit-id", "--name-only",
                      "--no-renames", "-z", head, commit)
        if set(changed.split(b"\0")) - {b"", *map(os.fsencode, paths)}:
            raise ValueError("The new commit contains an unselected path.")
        result["page_ids"] = committed_page_ids(head, commit)
        head = commit

    if head != tip:
        if line("symbolic-ref", "HEAD") != branch_ref or line("rev-parse", "HEAD") != head:
            raise ValueError("The checkout changed before push.")
        git(
            "push", "--no-follow-tags", "--recurse-submodules=no",
            f"--force-with-lease={branch_ref}:{tip}", "--", destination,
            f"{head}:{branch_ref}",
        )
        result["pushed"] = True
    result.update(status="ok", branch=branch, remote=remote)


def execute(value):
    result = {"status": "error", "commit": None, "pushed": False, "page_ids": []}
    try:
        paths, message = validate_input(value)
        if shutil.which("git") is None:
            raise ValueError("Git is required.")
        run(result, paths, message)
    except subprocess.CalledProcessError as error:
        result["error"] = error.stderr[:1024].decode(errors="replace").strip() or (
            f"Git exited with status {error.returncode}."
        )
    except subprocess.TimeoutExpired:
        result["error"] = "Git timed out after 60 seconds. Check the checkout and remote before retrying."
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["error"] = str(error)
    return result
