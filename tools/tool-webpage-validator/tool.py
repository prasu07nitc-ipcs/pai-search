"""Extract and validate an HTTP(S) URL from text without network requests.

Executed only through the shared project runner and its sandbox. The parent owns
logs; this module writes only its declared output directory.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _validate(url: str):
    try:
        if not url or len(url) > 8192 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            raise ValueError()
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError()
        if parts.username is not None or parts.password is not None or "\\" in url:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
        if "%" in host:
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.rstrip(".").split(".")
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in labels
            ):
                raise ValueError()
        port = parts.port
        if parts.netloc.endswith(":") or port == 0:
            raise ValueError()
        return parts, host, port or (443 if parts.scheme == "https" else 80)
    except (ValueError, UnicodeError):
        raise _Failure("invalid_url", "Provide a valid absolute HTTP(S) URL without credentials.") from None



def _extract_url(input_text: str) -> str:
    """Select the first valid explicit HTTP(S) candidate in textual order."""
    for match in re.finditer(r"(?<![\w+.-])https?://[^\s<>\"'`]+", input_text, re.IGNORECASE):
        candidate = match.group().split("](", 1)[0].rstrip(".,;:!?")
        # Remove prose/Markdown closing delimiters, preserving balanced URL ones.
        while candidate:
            closer = candidate[-1]
            opener = {")": "(", "]": "[", "}": "{"}.get(closer)
            if opener and candidate.count(closer) > candidate.count(opener):
                candidate = candidate[:-1].rstrip(".,;:!?")
            else:
                break
        try:
            _validate(candidate)
        except _Failure:
            continue
        return candidate
    raise _Failure("invalid_url", "No valid absolute HTTP(S) URL without credentials found in input_text.")


def validate_url(input_text: str) -> dict:
    """Extract the first valid explicit HTTP(S) URL and save its JSON identity.

    Preserve input_text verbatim; skip invalid candidates and strip surrounding
    prose punctuation. No DNS lookup or network request is performed.
    """
    result = {
        "input": {"input_text": input_text, "processed_input": {}},
        "output": None, "output_format": "json", "status": "error",
        "error": None, "meta_data": {},
    }
    try:
        url = _extract_url(input_text)
        payload = {"url": url, "page_id": hashlib.sha256(url.encode("utf-8")).hexdigest()}
        result["output"] = _write_output(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", payload["page_id"])
        result["meta_data"]["page_id"] = payload["page_id"]
        result["status"] = "ok"
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str, page_id: str) -> str:
    """Atomically replace <page_id>.json using a pinned tool-local directory."""
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    if re.fullmatch(r"[0-9a-f]{64}", page_id) is None:
        raise _Failure("output_write_error", "Output page_id is missing or invalid.")
    filename = f"{page_id}.json"
    descriptor = None
    temporary = None
    try:
        # Pin the directory without following symlinks. Exclusive temporary
        # creation plus flush/fsync/replace preserves an old result on failure.
        # Same-ID concurrent writes are last-replacement-wins; abrupt termination
        # can leave a temporary file for later cleanup.
        descriptor = os.open(tool_root / "output", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        name = f".output-{uuid.uuid4().hex}.tmp"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        temporary = name
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        return f"{tool_root.name}/output/{filename}"
    except OSError as exc:
        raise _Failure("output_write_error", "Could not save <page_id>.json in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)
