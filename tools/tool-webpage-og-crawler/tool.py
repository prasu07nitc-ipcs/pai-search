"""Fetch Open Graph properties, keywords, and dates; standard library only."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
from pathlib import Path
import uuid
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from typing import Literal, TypedDict
from urllib.parse import quote, urldefrag, urljoin, urlsplit


class CrawlError(TypedDict):
    code: str
    message: str


class _PayloadResult(TypedDict):
    requested_url: str | None
    final_url: str | None
    status: Literal["ok", "error"]
    open_graph: dict[str, str | None]
    keywords: str | None
    datePublished: str | None
    dateModified: str | None
    error: CrawlError | None


_PROPERTIES = ("og:title", "og:description", "og:image", "og:url", "og:site_name")
_LIMIT = 2 * 1024 * 1024
_SECONDS = 15.0


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str | None] = dict.fromkeys(_PROPERTIES)
        self.metadata: dict[str, str | None] = dict.fromkeys(
            ("keywords", "datePublished", "dateModified")
        )
        self._jsonld: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and (attributes.get("type") or "").lower().strip() == "application/ld+json":
            self._jsonld = []
        if tag != "meta":
            return
        key = attributes.get("property") or attributes.get("name")
        value = (attributes.get("content") or "").strip()
        if key in self.values and value and self.values[key] is None:
            self.values[key] = value
        aliases = {
            "keywords": "keywords", "datepublished": "datePublished",
            "datemodified": "dateModified", "article:published_time": "datePublished",
            "article:modified_time": "dateModified",
        }
        metadata_key = aliases.get((key or attributes.get("itemprop") or "").lower())
        if metadata_key and value and self.metadata[metadata_key] is None:
            self.metadata[metadata_key] = value

    def handle_data(self, data):
        if self._jsonld is not None:
            self._jsonld.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self._jsonld is None:
            return
        source = "".join(self._jsonld)
        self._jsonld = None
        try:
            document = json.loads(source)
        except (ValueError, RecursionError):
            return
        pending = [document]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(reversed(node))
            elif isinstance(node, dict):
                for key in self.metadata:
                    value = node.get(key)
                    if key == "keywords" and isinstance(value, list):
                        value = ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
                    if isinstance(value, str) and value.strip() and self.metadata[key] is None:
                        self.metadata[key] = value.strip()
                if "@graph" in node:
                    pending.append(node["@graph"])

    handle_startendtag = handle_starttag


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Failure("timeout", "The page could not be fetched within 15 seconds.")
    return remaining


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


def _addresses(host: str, port: int):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise _Failure("dns_error", "The hostname could not be resolved.") from None
    if not addresses:
        raise _Failure("dns_error", "The hostname returned no addresses.")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or ip.is_multicast or (mapped and not mapped.is_global):
            raise _Failure("blocked_address", "The URL resolves to a non-public address.")
    return addresses[0]


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, deadline):
        super().__init__(host, port, timeout=_remaining(deadline))
        self.address = address
        self.secure = secure
        self.deadline = deadline

    def connect(self):
        family, kind, protocol, _, address = self.address
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(_remaining(self.deadline))
            sock.connect(address)
            if self.secure:
                sock.settimeout(_remaining(self.deadline))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except BaseException:
            sock.close()
            raise


def _crawl_open_graph(url: str) -> _PayloadResult:
    """Fetch an absolute public HTTP(S) URL and return metadata or a structured error.

    No optional inputs. Uses a 15-second cooperative network budget, five redirects,
    and a 2-MiB body limit. A runner-enforced process timeout must also bound DNS.
    """
    result: _PayloadResult = {
        "requested_url": url if isinstance(url, str) else None,
        "final_url": None,
        "status": "error",
        "open_graph": dict.fromkeys(_PROPERTIES),
        "keywords": None,
        "datePublished": None,
        "dateModified": None,
        "error": None,
    }
    deadline = time.monotonic() + _SECONDS
    try:
        if not isinstance(url, str):
            raise _Failure("invalid_url", "URL must be a string.")
        _validate(url)
        current = urldefrag(url)[0]
        visited: set[str] = set()
        for hop in range(6):
            if current in visited:
                raise _Failure("redirect_error", "A redirect loop was detected.")
            visited.add(current)
            parts, host, port = _validate(current)
            address = _addresses(host, port)
            _remaining(deadline)
            connection = _PinnedConnection(host, port, address, parts.scheme == "https", deadline)
            try:
                target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
                if parts.query:
                    target += "?" + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
                result["final_url"] = current
                connection.request("GET", target, headers={
                    "User-Agent": "WebpageOGCrawler/1.0",
                    "Accept": "text/html, application/xhtml+xml",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                })
                network_socket = connection.sock
                network_socket.settimeout(_remaining(deadline))
                with connection.getresponse() as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader("Location")
                        if not location or hop == 5:
                            raise _Failure("redirect_error", "Redirect location missing or five-redirect limit exceeded.")
                        current = urldefrag(urljoin(current, location))[0]
                        continue
                    if not 200 <= response.status < 300:
                        raise _Failure("http_error", f"The server returned HTTP {response.status}.")
                    if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
                        raise _Failure("unsupported_content_type", "The response is not HTML.")
                    if response.getheader("Content-Encoding", "identity").strip().lower() != "identity":
                        raise _Failure("unsupported_encoding", "The server returned compressed content despite an identity request.")
                    chunks = bytearray()
                    while True:
                        # The response retains its socket even if HTTPConnection detaches it.
                        remaining = _remaining(deadline)
                        network_socket.settimeout(remaining)
                        block = response.read1(min(65536, _LIMIT + 1 - len(chunks)))
                        _remaining(deadline)
                        if not block:
                            if response.length not in (None, 0):
                                raise _Failure("network_error", "The response body ended prematurely.")
                            break
                        chunks.extend(block)
                        if len(chunks) > _LIMIT:
                            raise _Failure("response_too_large", "The HTML response exceeds 2 MiB.")
                    charset = response.headers.get_content_charset() or "utf-8"
                    try:
                        html = chunks.decode(charset, errors="replace")
                    except (LookupError, UnicodeError):
                        html = chunks.decode("utf-8", errors="replace")
                    parser = _Parser()
                    parser.feed(html)
                    parser.close()
                    _remaining(deadline)
                    result.update(status="ok", open_graph=parser.values, **parser.metadata)
                    return result
            finally:
                connection.close()
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    except (TimeoutError, socket.timeout):
        result["error"] = {"code": "timeout", "message": "The page could not be fetched within the time limit."}
    except ssl.SSLError:
        result["error"] = {"code": "tls_error", "message": "A secure connection could not be established."}
    except (OSError, http.client.HTTPException):
        result["error"] = {"code": "network_error", "message": "The HTTP request failed or the response was invalid."}
    return result


class CrawlInput(TypedDict):
    raw_input: str
    processed_input: dict[str, str]


class CrawlResult(TypedDict):
    input: CrawlInput
    output: str | None
    output_format: str
    status: Literal["ok", "error"]
    error: CrawlError | None
    meta_data: dict[str, str | None]


def crawl_open_graph(url: str, raw_input: str) -> CrawlResult:
    """Fetch metadata for a public URL, preserving the caller's original request.

    raw_input is a required string supplied by the caller; it is never interpreted.
    URL constraints and the 15-second network budget match _crawl_open_graph.
    Success atomically replaces tool-local outputs/<run_id>.txt with UTF-8 JSON text.
    Expected fetch/write failures return output=null and a structured error.
    """
    result: CrawlResult = {
        "input": {"raw_input": raw_input, "processed_input": {"url": url}},
        "output": None, "output_format": "json", "status": "error", "error": None,
        "meta_data": {"requested_url": url, "final_url": None},
    }
    payload = _crawl_open_graph(url)
    result["meta_data"]["final_url"] = payload["final_url"]
    if payload["status"] == "error":
        result["error"] = payload["error"]
        return result
    content = {key: payload[key] for key in
               ("open_graph", "keywords", "datePublished", "dateModified")}
    try:
        path = _write_output(json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        result.update(status="ok", output=path)
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str) -> str:
    """Atomically replace <run_id>.txt using a pinned tool-local directory."""
    tool_root = Path(__file__).resolve().parent
    run_id = os.environ.get("PROJECT_TOOL_RUN_ID", "")
    if re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", run_id) is None:
        raise _Failure("output_write_error", "Runner execution run_id is missing or invalid.")
    filename = f"{run_id}.txt"
    descriptor = None
    temporary = None
    try:
        descriptor = os.open(tool_root / "outputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
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
        return f"{tool_root.name}/outputs/{filename}"
    except OSError as exc:
        raise _Failure("output_write_error", "Could not save <run_id>.txt in the tool outputs directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)
