"""Scoped Git commits and pushes for the common transaction runner."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SCOPE = ("data/articles", "data/index", "data/queries")
CONFIG = Path(__file__).with_name("git-config.json")
PROJECT = CONFIG.resolve().parents[2]
def git(*args, input_bytes=None, index=None):
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
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


def check_paths(paths, scope):
    prefixes = tuple(os.fsencode(directory + "/") for directory in scope)
    for path in paths:
        if path and not path.startswith(prefixes):
            raise ValueError(f"Path outside commit scope: {os.fsdecode(path)!r}")


def changes(parent, commit):
    return git("diff-tree", "-r", "--no-commit-id", "--name-only",
               "--no-renames", "-z", parent, commit).split(b"\0")


def validate_input(value):
    if not isinstance(value, dict) or value.keys() != {"file_paths", "commit_message"}:
        raise ValueError("Supply file_paths and commit_message.")
    message = value["commit_message"]
    if not isinstance(message, str) or not message.strip() or "\0" in message:
        raise ValueError("commit_message must be a nonblank string without NUL characters.")
    message.encode("utf-8")
    paths = value["file_paths"]
    if not isinstance(paths, list):
        raise ValueError("file_paths must be a list.")
    for path in paths:
        if (
            not isinstance(path, str) or "\0" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError(f"Expected a repository-relative file path: {path!r}")
        check_paths([os.fsencode(path)], SCOPE)
    if len(paths) != len(set(paths)):
        raise ValueError("file_paths must not contain duplicates.")
    return paths, message


def check_selected_files(paths):
    for name in paths:
        path = Path(name)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError(f"Symlinked file path: {name!r}")
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError(f"Expected a regular, unaliased file: {name!r}")


def run(result, paths, message):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    author, email = (config[key] for key in ("author", "email"))
    for value in (author, email):
        if not isinstance(value, str) or not value.strip() or any(
            character in value for character in "\r\n\0<>"
        ):
            raise ValueError("Invalid Git identity in git-config.json.")
    identity = ("-c", f"user.name={author}", "-c", f"user.email={email}")

    if Path(line("rev-parse", "--show-toplevel")).resolve() != PROJECT:
        raise ValueError("Run from the root of the target repository.")
    source_ref = line("symbolic-ref", "HEAD")
    source = source_ref.removeprefix("refs/heads/")
    if not source_ref.startswith("refs/heads/") or source.startswith("data-"):
        raise ValueError("Run from a working branch.")
    branch = f"data-{source}"
    branch_ref = f"refs/heads/{branch}"
    local = line("for-each-ref", "--format=%(objectname) %(refname)", branch_ref)
    previous = next((oid for oid, ref in (entry.split(" ", 1)
                     for entry in local.splitlines()) if ref == branch_ref), "")
    if not previous:
        raise ValueError(f"Missing paired data branch {branch!r}. Run paired branch setup first.")
    check_selected_files(paths)

    remotes = line("remote").splitlines()
    if not remotes:
        raise ValueError("The repository has no configured remote.")
    configured_remote = line(
        "for-each-ref", "--format=%(upstream:remotename)", source_ref
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
    if any(entry.endswith(f"branch {branch_ref}") for entry in
           line("worktree", "list", "--porcelain").splitlines()):
        raise ValueError("The paired data branch is checked out in another worktree.")
    head = previous
    new_commit = None
    with tempfile.TemporaryDirectory(prefix="pai-data-index-") as temp:
        index = Path(temp) / "index"
        git("read-tree", head, index=index)
        check_selected_files(paths)
        for path in paths:
            blob = line("hash-object", "-w", "--no-filters", "--", path)
            entry = b"100644 " + blob.encode("ascii") + b"\t" + os.fsencode(path) + b"\0"
            git("update-index", "-z", "--index-info", input_bytes=entry, index=index)
        tree = os.fsdecode(git("write-tree", index=index)).strip()
        if tree != line("rev-parse", f"{head}^{{tree}}"):
            commit = line(*identity, "-c", "commit.gpgSign=false", "commit-tree",
                          tree, "-p", head, "-m", message)
            changed = set(changes(head, commit)) - {b""}
            if not changed <= set(map(os.fsencode, paths)):
                raise ValueError("The new commit contains an unselected path.")
            result["page_ids"] = sorted({
                os.fsdecode(match[1])
                for path in changed
                if (match := re.fullmatch(
                    rb"data/(?:articles/[^/]+|index/[^/]+/[^/]+)/([0-9a-f]{64})\.md", path
                ))
            })
            new_commit = head = commit

    if line("symbolic-ref", "HEAD") != source_ref:
        raise ValueError("The working branch changed during validation.")
    git("update-ref", branch_ref, head, previous or "0" * len(head))
    result.update(branch=branch, remote=remote, commit=new_commit)
    if head != tip:
        git("push", "--no-follow-tags", "--recurse-submodules=no",
            "--", destination,
            f"{head}:{branch_ref}")
        result["pushed"] = True
    advertised_tip = line("ls-remote", "--heads", "--", destination, branch_ref)
    if advertised_tip != f"{head}\t{branch_ref}":
        raise ValueError("Could not verify the published remote branch tip.")
    result["verified_file_paths"] = paths
    result["status"] = "ok"


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
