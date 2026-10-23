"""Store supplied webpage metadata as an agent-readable local bookmark."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _domain(url: str) -> str:
    try:
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError()
        if parsed.port == 0 or parsed.netloc.endswith(":"):
            raise ValueError()
        return host
    except (ValueError, UnicodeError):
        raise _Failure("invalid_url", "url must be an absolute HTTP(S) URL with a valid hostname and no credentials.") from None


def _text(value: str) -> str:
    # Keep supplied text on one line, escaping Markdown control characters.
    return re.sub(r"([\\`*_{}\[\]<>#+|])", r"\\\1", " ".join(value.split()))


def _render(page: dict, domain: str) -> str:
    lines = ["# " + _text(page["title"]), "", "## Description", "", _text(page["description"]), "", "## Source", ""]
    for label, value in [("URL", page["url"]), ("Domain", domain)] + [(label, page.get(key)) for label, key in [("Site name", "site_name"), ("Type", "type"), ("Section", "section")]]:
        if value:
            lines.append(f"- {label}: {_text(value)}")
    keywords = list(dict.fromkeys(word.strip() for word in (page.get("keywords") or "").split(",") if word.strip()))
    if keywords:
        lines += ["", "## Keywords", ""] + ["- " + _text(word) for word in keywords]
    dates = [(label, page.get(key)) for label, key in [("Published", "datePublished"), ("Modified", "dateModified")]]
    if any(value for _, value in dates):
        lines += ["", "## Dates", ""] + [f"- {label}: {_text(value)}" for label, value in dates if value]
    lines += ["", "## Identifier", "", "- Page ID: " + page["page_id"], ""]
    return "\n".join(lines).rstrip("\n") + "\n\n" + os.environ["PROJECT_TRANSACTION_SIGNATURE_MARKDOWN"]


def _open_data_directory() -> int:
    """Open the runner-prepared data destination without following symlinks.

    The runner supplies an absolute canonical production directory. This configuration does not replace OS isolation.
    """
    configured = os.environ.get("PROJECT_TRANSACTION_DATA_DIRECTORY", "")
    path = Path(configured)
    if not configured or not path.is_absolute() or path.name != "bookmark" or ".." in path.parts or str(path) != configured:
        raise _Failure("output_write_error", "Runner must supply the prepared absolute bookmark data directory.")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_output(domain: str, page_id: str, content: str) -> str:
    """Atomically replace the page bookmark within the prepared data directory."""
    folder = domain.replace(".", "_")
    filename = page_id + ".md"
    parent = descriptor = None
    temporary = None
    try:
        parent = _open_data_directory()
        try:
            os.mkdir(folder, dir_fd=parent)
        except FileExistsError:
            pass
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            existing = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise OSError("Unsafe existing bookmark target")
        except FileNotFoundError:
            pass
        name = f".bookmark-{uuid.uuid4().hex}.tmp"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        temporary = name
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        return f"data/bookmark/{folder}/{filename}"
    except OSError as exc:
        raise _Failure("output_write_error", "Could not atomically save the bookmark in the prepared data directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        for opened in (descriptor, parent):
            if opened is not None:
                os.close(opened)


def _source_file(path, component):
    root = Path(os.environ['PROJECT_TRANSACTION_INPUT_ROOT'])
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    expected = root / component / 'output'
    try:
        # Require a direct output file; do not follow aliases into or out of it.
        if (not path.strip() or '..' in source.parts
                or source.parent != expected
                or source.resolve() != source
                or source.suffix != '.txt'
                or re.fullmatch(r'[0-9a-f]{64}', source.stem) is None):
            raise ValueError('Not a component output path')
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Not a regular unaliased file')
        return source
    except (OSError, ValueError, RuntimeError) as exc:
        raise _Failure('invalid_input_source', 'Input must be a regular ' + component
                       + '/output/<run_id>.txt file: ' + path) from exc


def _read_input(source):
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r', encoding='utf-8', newline='') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError('Input must be a regular unaliased file')
            return stream.read()
    except (OSError, UnicodeError, ValueError) as exc:
        raise _Failure('input_read_error', 'Could not read UTF-8 input file: ' + str(source)) from exc


def bookmark(page_file: str, raw_input: str) -> dict:
    """Save JSON metadata; require title, description, URL and SHA-256 page ID.

    Optional recognized fields are strings or null; additional JSON fields are
    accepted but not rendered. No network access or dependency installation occurs.
    """
    result = {"input": {"raw_input": raw_input, "processed_input": {"page_file": page_file}}, "output": None, "output_format": "markdown", "status": "error", "error": None, "meta_data": {}}
    try:
        source = _source_file(page_file, 'tools/tool-webpage-og-crawler')
        try:
            page = json.loads(_read_input(source))
        except (ValueError, RecursionError) as exc:
            raise _Failure('invalid_json', 'Crawler output must contain a JSON object.') from exc
        if not isinstance(page, dict):
            raise _Failure('invalid_json', 'Crawler output must contain a JSON object.')
        for field in ("title", "description", "url", "page_id"):
            if not isinstance(page.get(field), str) or not page[field].strip():
                raise _Failure("invalid_input", f"{field} must be a nonempty string.")
        if re.fullmatch(r"[0-9a-f]{64}", page["page_id"]) is None:
            raise _Failure("invalid_page_id", "page_id must contain exactly 64 lowercase hexadecimal characters.")
        for field in ("site_name", "type", "section", "keywords", "datePublished", "dateModified", "image"):
            if page.get(field) is not None and not isinstance(page[field], str):
                raise _Failure("invalid_input", f"{field} must be a string or null when supplied.")
        domain = _domain(page["url"])
        content = _render(page, domain)
        result["output"] = [_write_output(domain, page["page_id"], content)]
        result.update(status="ok", meta_data={"domain": domain, "page_id": page["page_id"]})
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result
