"""Export saved search reports into the data catalog."""
import fcntl
import os
from pathlib import Path
import re
import stat
import uuid

_REPORT_NAME = re.compile(r"([0-9a-f]{64})\.(md|txt)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_PATH_TOKEN = re.compile(
    r"""(?<![^\s(\[<`"'=])[^\s\[\]()<>\x60"']+/[^\s\[\]()<>\x60"']+"""
    r"""|(?<![^\s(\[<`"'=])/(?!/)[^\s\[\]()<>\x60"']+"""
    r"""|(?<=\]\()(?!#|<)[^\s\[\]()<>\x60"']+"""
)
_URL = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def _catalog_markdown(markdown, data_root):
    lines = []
    references_level = None
    for line in markdown.splitlines(keepends=True):
        heading = _HEADING.fullmatch(line.rstrip("\r\n"))
        if heading:
            level = len(heading[1])
            if references_level is not None and level <= references_level:
                references_level = None
            if references_level is None and heading[2].casefold() == "references":
                references_level = level
                continue
        if references_level is None:
            lines.append(line)
    def catalog_path(match):
        path = match[0]
        if (_URL.match(path) and not path.lower().startswith("file://")
                or path.lower().startswith("mailto:")):
            return path
        prefix = f"{data_root}/"
        if path.startswith(prefix):
            path = "data/" + path[len(prefix):]
        if not path.startswith("data/") or any(
            part in {"", ".", ".."} for part in path.split("/")[1:]
        ):
            raise ValueError(f"File path must be under data/: {match[0]}")
        return path

    return _PATH_TOKEN.sub(catalog_path, "".join(lines)).encode("utf-8")


def _check_regular(info, name):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Expected a regular, unlinked file: {name}")


def _read_report(directory, name, run_id, data_root):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        _check_regular(os.fstat(stream.fileno()), name)
        content = stream.read()
    markdown = content.decode("utf-8")
    before_id, separator, query_id = markdown.rpartition("\n# Query ID\n")
    sections = re.search(r"^# Response\n(.*?)^# Index Files Analysed:?\n(.*?)"
                         r"^# Execution [Tt]ime\n\s*\S",
                         before_id, re.MULTILINE | re.DOTALL)
    if (not markdown.startswith("# Query\n") or sections is None
            or not sections[1].strip()
            or not sections[2].strip()
            or not before_id[len("# Query\n"):sections.start()].strip()
            or not separator or query_id.strip() != run_id):
        raise ValueError(f"Invalid search report or mismatched Query ID: {name}")
    return _catalog_markdown(markdown, data_root)


def export_searches() -> dict:
    result = {
        "input": {"raw_input": None, "processed_input": {}},
        "output": None, "output_format": "markdown", "status": "error",
        "error": None, "meta_data": {},
    }
    source_path = Path(os.environ["PROJECT_TRANSACTION_INPUT_ROOT"]) / "skills/skill-webpage-search/output"
    target_path = Path(os.environ["PROJECT_TRANSACTION_DATA_DIRECTORY"])
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    written = []
    staged = []
    try:
        target = os.open(target_path, directory_flags)
        try:
            fcntl.flock(target, fcntl.LOCK_EX)
            source = os.open(source_path, directory_flags)
            try:
                pending = {}
                for name in sorted(os.listdir(source)):
                    match = _REPORT_NAME.fullmatch(name)
                    if match is None:
                        continue
                    run_id = match[1]
                    try:
                        os.stat(f"{run_id}.md", dir_fd=target, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        continue
                    if run_id in pending:
                        raise ValueError(f"Multiple search reports for {run_id}.")
                    pending[run_id] = name
                for run_id, source_name in pending.items():
                    content = _read_report(source, source_name, run_id, target_path.parent)
                    name = f"{run_id}.md"
                    temporary = f".webpage-search-{uuid.uuid4().hex}.tmp"
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=target)
                    staged.append((temporary, name))
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
            finally:
                os.close(source)
            for temporary, name in staged:
                os.replace(temporary, name, src_dir_fd=target, dst_dir_fd=target)
                written.append(f"data/queries/{name}")
                os.fsync(target)
        finally:
            try:
                for temporary, _ in staged:
                    try:
                        os.unlink(temporary, dir_fd=target)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(target)
    except (OSError, ValueError) as exc:
        result["error"] = {"code": "export_failed", "message": str(exc)}
        if written:
            result["meta_data"]["affected_paths"] = written
        return result
    result.update(output=written, status="ok", meta_data={"report_count": len(written)})
    return result
