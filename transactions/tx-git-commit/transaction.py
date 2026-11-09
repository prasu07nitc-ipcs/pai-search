"""Scoped Git commits and pushes for the common transaction runner."""

import json
import os
from pathlib import Path
import shutil
import subprocess

SCOPE = ("data/articles", "data/index", "data/queries")
CONFIG = Path(__file__).with_name("git-config.json")


def git(*args):
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    result = subprocess.run(
        ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", *args],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout


def line(*args):
    return os.fsdecode(git(*args)).rstrip("\n")


def check_paths(paths):
    prefixes = tuple(os.fsencode(directory + "/") for directory in SCOPE)
    for path in paths.split(b"\0"):
        if path and not path.startswith(prefixes):
            raise ValueError(f"Path outside commit scope: {os.fsdecode(path)!r}")


def check_worktree():
    entries = git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all",
        "--no-renames", "--ignore-submodules=none",
    ).split(b"\0")
    check_paths(b"\0".join(entry[3:] for entry in entries if entry))


def run(message, result):
    if not message.strip() or "\0" in message:
        raise ValueError("Supply a nonempty commit message.")
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
    if any(Path(line("rev-parse", "--git-path", marker)).exists() for marker in (
        "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
        "rebase-apply", "sequencer",
    )):
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
    heads = dict((ref, oid) for oid, ref in (
        entry.split("\t", 1) for entry in advertised.splitlines()
    ))
    tip = heads.get(branch_ref, "")
    bases = [tip] if tip else sorted(set(heads.values()))
    if bases:
        git("fetch", "--no-tags", "--no-write-fetch-head", "--", destination, *bases)
    if tip:
        git("merge-base", "--is-ancestor", tip, head)
    exclusions = ["--not", *bases] if bases else []
    for commit in line("rev-list", head, *exclusions).splitlines():
        check_paths(git(
            "diff-tree", "--root", "-m", "-r", "--no-commit-id",
            "--name-only", "--no-renames", "-z", commit,
        ))

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
        git("add", "-A", "--", *paths)
    staged = git("diff", "--cached", "--name-only", "--no-renames", "-z")
    check_paths(staged)
    if staged:
        git(
            "-c", f"user.name={author}", "-c", f"user.email={email}",
            "-c", "commit.gpgSign=false", "commit", "--author",
            f"{author} <{email}>", "-m", message,
        )
        head = line("rev-parse", branch_ref)
        result["commit"] = head
        check_paths(git(
            "diff-tree", "-r", "--no-commit-id", "--name-only", "--no-renames",
            "-z", head + "^", head,
        ))

    if head != tip:
        if line("symbolic-ref", "HEAD") != branch_ref or line("rev-parse", "HEAD") != head:
            raise ValueError("The checkout changed before push.")
        git(
            "-c", "push.followTags=false", "push", "--no-follow-tags",
            f"--force-with-lease={branch_ref}:{tip}", "--", destination,
            f"{head}:{branch_ref}",
        )
        result["pushed"] = True
    result.update(status="ok", branch=branch, remote=remote)


def execute(value):
    result = {"status": "error", "commit": None, "pushed": False}
    try:
        if not isinstance(value, dict) or value.keys() != {"message"} or not isinstance(value["message"], str):
            raise ValueError('Supply an object containing exactly one string field, "message".')
        if shutil.which("git") is None:
            raise ValueError("Git is required.")
        run(value["message"], result)
    except subprocess.CalledProcessError as error:
        result["error"] = error.stderr.decode(errors="replace").strip() or (
            f"Git exited with status {error.returncode}."
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["error"] = str(error)
    return result
