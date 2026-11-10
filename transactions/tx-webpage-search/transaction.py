"""Export saved search reports into the data catalog."""
import fcntl
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit

_REPORT_NAME = re.compile(r"([0-9a-f]{64})\.(md|txt)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_PATH_TOKEN = re.compile(
    r"""(?<![^\s(\[<`"'=])[^\s\[\]()<>\x60"']+/[^\s\[\]()<>\x60"']+"""
    r"""|(?<![^\s(\[<`"'=])/(?!/)[^\s\[\]()<>\x60"']+"""
    r"""|(?<=\]\()(?!#|<)[^\s\[\]()<>\x60"']+"""
)
_URL = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def _catalog_markdown(markdown, data_root):
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

    return _PATH_TOKEN.sub(catalog_path, markdown)


def _check_regular(info, name):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Expected a regular, unlinked file: {name}")


_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\((?:<([^>\n]+)>|([^\s()]+))\)")
_REFERENCE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_ARTICLE = re.compile(r"data/articles/([^/]+)/([0-9a-f]{64}\.md)")
_INDEX = re.compile(r"data/index/[^/]+/[^/]+/[0-9a-f]{64}\.md")
_SEQUENCE = re.compile(r"\s+(?:#\d+|\(#?\d+\)|\[\d+\])$")


def _local_path(link, data_root):
    path = link[2] or link[3]
    prefix = f"{data_root}/"
    return "data/" + path[len(prefix):] if path.startswith(prefix) else path


def _article_webpage(path, data_root):
    match = _ARTICLE.fullmatch(path)
    if match is None or match[1] in {".", ".."}:
        raise ValueError(f"Invalid article reference: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    articles = os.open(data_root / "articles", flags)
    try:
        domain = os.open(match[1], flags, dir_fd=articles)
        try:
            fd = os.open(match[2], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=domain)
            with os.fdopen(fd, encoding="utf-8") as stream:
                _check_regular(os.fstat(stream.fileno()), path)
                _, separator, footer = stream.read().rpartition("\n## Meta Data\n")
        finally:
            os.close(domain)
    finally:
        os.close(articles)
    urls = re.findall(r"^- \*\*url:\*\* (.+)$", footer, re.MULTILINE)
    if separator and len(urls) == 1:
        url = urls[0]
        if not re.search(r"[\s\x00-\x1f\x7f\\<>]", url):
            parsed = urlsplit(url)
            if (parsed.scheme in {"http", "https"} and parsed.hostname
                    and parsed.username is None and parsed.password is None
                    and parsed.port != 0):
                return url, match[2].removesuffix(".md")
    raise ValueError(f"Expected one valid article metadata URL: {path}")


def _sources(response, data_root):
    entities = {}
    webpages = {}
    articles = set()
    references_level = None
    for line in response.splitlines():
        heading = _HEADING.fullmatch(line)
        if heading:
            level = len(heading[1])
            if references_level is not None and level <= references_level:
                references_level = None
            if heading[2].casefold() == "references":
                references_level = level
                continue
        if references_level is None:
            for link in _LINK.finditer(line):
                if _INDEX.fullmatch(_local_path(link, data_root)):
                    entity = _SEQUENCE.sub("", link[1]).strip()
                    if entity:
                        entities.setdefault(entity.casefold(), entity)
        elif not heading and (entry := _REFERENCE.fullmatch(line)):
            link = _LINK.fullmatch(entry[1])
            if link is None:
                raise ValueError(f"Invalid article reference: {line}")
            path = _local_path(link, data_root)
            if path not in articles:
                url, page_id = _article_webpage(path, data_root)
                webpages.setdefault(url, page_id)
                articles.add(path)
    return entities.values(), webpages


def _bullet_list(items):
    return "".join(f"- {item}\n" for item in items)


def _read_report(directory, name, run_id, data_root):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        _check_regular(os.fstat(stream.fileno()), name)
        content = stream.read()
    markdown = content.decode("utf-8")
    before_id, separator, query_id = markdown.rpartition("\n# Query ID\n")
    sections = re.search(r"^# Response\n(.*?)^# Index Files Analysed:?\n(.*?)"
                         r"(^# Execution [Tt]ime:?\n\s*\S)",
                         before_id, re.MULTILINE | re.DOTALL)
    if (not markdown.startswith("# Query\n") or sections is None
            or not sections[1].strip()
            or not sections[2].strip()
            or not before_id[len("# Query\n"):sections.start()].strip()
            or not separator or query_id.strip() != run_id):
        raise ValueError(f"Invalid search report or mismatched Query ID: {name}")
    entities, webpages = _sources(sections[1], data_root)
    query = _catalog_markdown(markdown[:sections.start()], data_root)
    execution = _catalog_markdown(markdown[sections.start(3):], data_root)
    return (query + "# Entities\n" + _bullet_list(entities)
            + "\n# Webpages\n"
            + _bullet_list(f"[{page_id}](<{url}>)" for url, page_id in webpages.items())
            + "\n" + execution).encode("utf-8")


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
