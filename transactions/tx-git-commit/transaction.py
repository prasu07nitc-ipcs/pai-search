"""Scoped Git commits and pushes for the common transaction runner."""

from datetime import datetime
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


def clean_tool_outputs(page_ids):
    completed = subprocess.run(
        ["tools/.venv/bin/python", "-B", "tools/runner.py", "--tool", "tool-webpage-gc",
         "--input", json.dumps({"page_ids": page_ids}, separators=(",", ":"))],
        cwd=PROJECT, capture_output=True, encoding="utf-8", timeout=60,
    )
    if completed.returncode:
        raise ValueError("Webpage cleanup runner exited with status "
                         f"{completed.returncode}. See tools/tool-webpage-gc/logs/runner.log.")
    return json.loads(completed.stdout)


def run(result):
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
    # Filter absent directories so a sparse set of generated outputs is valid.
    tracked = git("ls-files", "-z", "--", *SCOPE).split(b"\0")
    paths = [
        directory for directory in SCOPE if Path(directory).is_dir()
        or any(path.startswith(os.fsencode(directory + "/")) for path in tracked)
    ]
    if paths:
        git("add", "-f", "-A", "--", *paths)
    staged = git("diff", "--cached", "--name-only", "--no-renames", "-z")
    check_paths(staged.split(b"\0"))
    if staged:
        message = datetime.now().strftime("%d-%m-%y")
        git(
            "-c", f"user.name={author}", "-c", f"user.email={email}",
            "-c", "commit.gpgSign=false", "commit", "--author",
            f"{author} <{email}>", "-m", message,
        )
        commit = line("rev-parse", branch_ref)
        result["commit"] = commit
        if line("rev-list", "--parents", "-n", "1", commit).split() != [commit, head]:
            raise ValueError("The new commit does not have the expected parent.")
        check_history(commit, [head])
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
    if result["page_ids"]:
        try:
            result["cleanup"] = clean_tool_outputs(result["page_ids"])
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"Commit was pushed, but webpage cleanup failed: {error}") from error
        if result["cleanup"]["status"] != "ok":
            raise ValueError("Commit was pushed, but webpage cleanup reported an error.")
    result.update(status="ok", branch=branch, remote=remote)


def execute(value):
    result = {"status": "error", "commit": None, "pushed": False, "page_ids": [], "cleanup": None}
    try:
        if not isinstance(value, dict) or value.keys() - {"message"} or not isinstance(value.get("message", ""), str):
            raise ValueError('Supply an empty object or an object with only a string "message".')
        if shutil.which("git") is None:
            raise ValueError("Git is required.")
        run(result)
    except subprocess.CalledProcessError as error:
        result["error"] = error.stderr[:1024].decode(errors="replace").strip() or (
            f"Git exited with status {error.returncode}."
        )
    except subprocess.TimeoutExpired:
        result["error"] = "Git timed out after 60 seconds. Check the checkout and remote before retrying."
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["error"] = str(error)
    return result
