"""Store supplied webpage metadata as an agent-readable local bookmark."""
from __future__ import annotations

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
    return "\n".join(lines).rstrip("\n") + "\n"


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


def _write_output(domain: str, page_id: str, contents: dict, written: list) -> list:
    """Stage a page's bookmark and metadata, then atomically replace each file."""
    folder = domain.replace(".", "_")
    descriptor = None
    staged = {}
    try:
        descriptor = _open_data_directory()
        for component in (folder, page_id):
            try:
                os.mkdir(component, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        for filename, content in contents.items():
            try:
                existing = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                    raise OSError("Unsafe existing bookmark target")
            except FileNotFoundError:
                pass
            temporary = f".bookmark-{uuid.uuid4().hex}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptor)
            staged[filename] = temporary
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        for filename, temporary in list(staged.items()):
            os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            del staged[filename]
            written.append(f"data/bookmark/{folder}/{page_id}/{filename}")
        os.fsync(descriptor)
        return written
    except (OSError, UnicodeError) as exc:
        raise _Failure("output_write_error", "Could not save bookmark and metadata; retry the complete pair after a partial replacement.") from exc
    finally:
        if descriptor is not None:
            for temporary in staged.values():
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except OSError:
                    pass
            os.close(descriptor)


def bookmark(page: dict) -> dict:
    """Save JSON metadata; require title, description, URL and SHA-256 page ID.

    Optional recognized fields are strings or null; additional JSON fields are
    accepted but not rendered. No network access or dependency installation occurs.
    """
    result = {"input": {"raw_input": None, "processed_input": page}, "output": None, "output_format": "markdown", "status": "error", "error": None, "meta_data": {}}
    written = []
    try:
        if not isinstance(page, dict):
            raise _Failure("invalid_input", "page must be a JSON object.")
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
        metadata = "## Identifier\n\n- Page ID: " + page["page_id"] + "\n\n" + os.environ["PROJECT_TRANSACTION_SIGNATURE_MARKDOWN"]
        result["output"] = _write_output(domain, page["page_id"],
            {"bookmark.md": content, "meta.md": metadata}, written)
        result.update(status="ok", meta_data={"domain": domain, "page_id": page["page_id"]})
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
        if written:
            result["meta_data"] = {"affected_paths": written}
    return result
