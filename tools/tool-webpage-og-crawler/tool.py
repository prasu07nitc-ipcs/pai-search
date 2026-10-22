"""Fetch Open Graph properties, keywords, and dates; standard library only.

Runtime integration (owned by the shared runner, not this module):
Use only tools/.venv/bin/python through tools/runner.py with an explicit tool
selection and working directory. The runner verifies sys.prefix and input binding,
then applies and probes the macOS filesystem/subprocess sandbox before import.
Workers may write only in their validated tool-local output/ directory, and cannot
fork/exec or mutate the environment. The parent validates/prepares output/ and
owns all log writes; this module does not implement sandbox enforcement.

The parent writes production results to logs/run.log, test results to
logs/test-report.log, and diagnostics/timing to logs/runner.log under this tool.
Record formats and run-ID rules: tools/AGENTS.md#production-logging. Tests use
UUIDs; production IDs hash supplied input. The runner supplies PROJECT_TOOL_RUN_ID
before import. Historical logs and outputs are not rewritten automatically.

From the parent project directory containing tools/, select this tool with the
absolute project interpreter and runner paths. --input accepts named JSON
arguments; --cases accepts this tool's test-cases.json. --summary emits compact
test counts; inspect failed cases (CLI exit 1), not just process completion.
The runner loads validator.py only for tests and enforces the production envelope
without loading test code. Do not install/repair dependencies during execution.

Select --tool tool-webpage-og-crawler; keep the process timeout at least 20
seconds (the runner default). Python 3.11+ standard library only.
"""

from __future__ import annotations

import hashlib
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
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
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


_PROPERTIES = ("og:title", "og:description", "og:image", "og:url", "og:site_name", "og:type", "article:section")
# Identity encoding avoids decompression beyond the 2-MiB body cap.
# Socket deadlines bound individual operations; blocking DNS additionally needs
# the runner process timeout (default 20s, configurable up to 300s).
_LIMIT = 2 * 1024 * 1024
_SECONDS = 15.0


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Explicit date labels only: separator/case variants are normalized, not inferred.
_DATE_LABELS = {
    "datePublished": {
        "datepublished", "published", "publisheddate", "publishedtime",
        "publishedat", "publishdate", "publishtime", "publicationdate",
        "publicationtime", "pubdate", "dtpublished", "originalpublicationdate",
        "articlepublished", "articlepublisheddate", "articlepublishedtime",
        "articlepublicationdate", "ogarticlepublished", "ogarticlepublishedtime",
        "ogdatepublished", "ogpubdate", "ogpublishdate", "ogpublishedtime",
        "rnewsdatepublished", "citationpublicationdate", "dcdateissued",
        "dcdatepublication", "dctermsissued", "dcissued",
        "dcsextarticlefirstpublished", "parselypubdate", "btpubdate",
        "shareaholicarticlepublishedtime", "mediatorpublishedtime",
        "cxenseparserecspublishtime", "twtpublishedat", "vrpublishedtime",
    },
    "dateModified": {
        "dtupdated", "datemodified", "dateupdated", "dateupdate", "modified", "updated",
        "modifieddate", "modifiedtime", "modifiedat", "updateddate",
        "updatedtime", "updatedat", "updatedate", "updatetime",
        "lastmodified", "lastmodifieddate", "lastmodifiedtime", "lastmod",
        "lastupdated", "lastupdateddate", "lastupdatedtime", "lastupdate",
        "modificationdate", "modificationtime", "revisiondate",
        "articlemodified", "articlemodifieddate", "articlemodifiedtime",
        "articlepostmodified", "articleupdatedtime", "ogarticlemodifiedtime",
        "ogmodifiedtime", "ogupdatedtime", "ogdatemodified",
        "dcmodified", "dcdatemodified", "dctermsmodified",
        "rnewsdatemodified", "btmoddate",
    },
}
_DATE_FIELDS = {label: field for field, labels in _DATE_LABELS.items() for label in labels}


def _date_field(label: str) -> str | None:
    # Schema.org URLs/CURIEs use the same local names as plain microdata keys.
    label = label.strip().lower()
    for prefix in ("https://schema.org/", "http://schema.org/", "schema:"):
        if label.startswith(prefix):
            label = label[len(prefix):]
            break
    return _DATE_FIELDS.get(re.sub(r"[\s:._-]+", "", label))


def _normalize_date(value: str | None) -> tuple[str | None, dict]:
    """Normalize explicit dates without guessing ambiguous numeric order."""
    info = {"raw_value": value, "status": "missing", "assumptions": []}
    if value is None:
        return None, info
    text = value.strip()
    info["status"] = "invalid"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            day = date.fromisoformat(text)
        elif re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", text):
            first, second, year = map(int, re.split(r"[-/]", text))
            if 1 <= first <= 12 and 1 <= second <= 12 and first != second:
                info["status"] = "ambiguous"
                return None, info
            month, day_number = (second, first) if first > 12 else (first, second)
            day = date(year, month, day_number)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", text):
            offset = re.search(r"[+-](\d{2}):(\d{2})$", text)
            if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                return None, info
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                info["status"] = "preserved" if "T" in text else "normalized"
                return text if "T" in text else stamp.isoformat(), info
            info.update(status="normalized", assumptions=["timezone_utc"])
            return stamp.replace(tzinfo=timezone.utc).isoformat(), info
        else:
            day = None
            for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
                try:
                    day = datetime.strptime(text, pattern).date()
                    break
                except ValueError:
                    pass
            if day is None:
                # RFC 2822 timestamps must explicitly provide an offset or UTC/GMT.
                if not re.search(r"(?:[+-]\d{4}|UTC|GMT)$", text):
                    return None, info
                offset = re.search(r"[+-](\d{2})(\d{2})$", text)
                if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                    return None, info
                stamp = parsedate_to_datetime(text)
                if stamp.tzinfo is None:
                    return None, info
                info["status"] = "normalized"
                return stamp.isoformat(), info
        info.update(status="normalized", assumptions=["time_midnight", "timezone_utc"])
        return datetime.combine(day, datetime.min.time(), timezone.utc).isoformat(), info
    except (ValueError, TypeError, OverflowError):
        return None, info


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
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            value = (attributes.get("content") or "").strip()
            if key in self.values and value and self.values[key] is None:
                self.values[key] = value
            metadata_key = (key or attributes.get("itemprop") or "").lower()
            if metadata_key == "keywords" and value and self.metadata["keywords"] is None:
                self.metadata["keywords"] = value
        else:
            value = (attributes.get("content") or attributes.get("datetime") or "").strip()
        if not value:
            return
        # Inspect every semantic attribute so an unrelated name cannot hide itemprop.
        # A time element may additionally label its datetime using class/id tokens.
        for attribute in ("property", "name", "itemprop", "http-equiv"):
            label = attributes.get(attribute) or ""
            labels = label.split() if attribute in ("property", "itemprop") else [label]
            for item in labels:
                field = _date_field(item)
                if field and self.metadata[field] is None:
                    self.metadata[field] = value
        if tag == "time":
            for label in ((attributes.get("class") or "").split() + [attributes.get("id") or ""]):
                field = _date_field(label)
                if field and self.metadata[field] is None:
                    self.metadata[field] = value

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
                for key, value in node.items():
                    field = "keywords" if key == "keywords" else _date_field(key)
                    if not field:
                        continue
                    if field == "keywords" and isinstance(value, list):
                        value = ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
                    if isinstance(value, str) and value.strip() and self.metadata[field] is None:
                        self.metadata[field] = value.strip()
                # Follow article/page relationships, not author/review/product dates.
                children = [node[key] for key in ("@graph", "mainEntity", "mainEntityOfPage") if key in node]
                pending.extend(reversed(children))

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
    # Reject a mixed public/private DNS answer, then pin the first validated IP.
    # This prevents later connection-time DNS resolution from changing the target.
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
                # Fixed Firefox-style identity for site compatibility; this is
                # still an HTTP client with no browser rendering or browser state.
                connection.request("GET", target, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:138.0) Gecko/20100101 Firefox/138.0",
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
                    # Decode the declared charset; absent/unknown labels fall back
                    # to UTF-8 with replacement rather than aborting extraction.
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
    meta_data: dict


def crawl_open_graph(url: str, raw_input: str) -> CrawlResult:
    """Fetch metadata for a public URL, preserving the caller's original request.

    raw_input is a required string supplied by the caller; it is never interpreted.
    URL constraints and the 15-second network budget match _crawl_open_graph.
    Success atomically replaces tool-local output/<run_id>.txt with UTF-8 JSON text.
    Expected fetch/write failures return output=null and a structured error.
    """
    result: CrawlResult = {
        "input": {"raw_input": raw_input, "processed_input": {"url": url}},
        "output": None, "output_format": "json", "status": "error", "error": None,
        "meta_data": {"requested_url": url, "final_url": None, "date_normalization": {}},
    }
    payload = _crawl_open_graph(url)
    result["meta_data"]["final_url"] = payload["final_url"]
    if payload["status"] == "error":
        result["error"] = payload["error"]
        return result
    content = {key.split(":", 1)[-1]: item for key, item in payload["open_graph"].items()}
    content.update({key: payload[key] for key in ("keywords", "datePublished", "dateModified")})
    for field in ("datePublished", "dateModified"):
        content[field], info = _normalize_date(content[field])
        result["meta_data"]["date_normalization"][field] = info
    content["page_id"] = hashlib.sha256(content["url"].encode("utf-8")).hexdigest() if content["url"] is not None else None
    try:
        path = _write_output(json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        result.update(status="ok", output=path)
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str) -> str:
    """Atomically replace <run_id>.txt using a pinned tool-local directory."""
    # Runner-supplied IDs allow SHA-256 production inputs and UUID test runs.
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    run_id = os.environ.get("PROJECT_TOOL_RUN_ID", "")
    if re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", run_id) is None:
        raise _Failure("output_write_error", "Runner execution run_id is missing or invalid.")
    filename = f"{run_id}.txt"
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
        raise _Failure("output_write_error", "Could not save <run_id>.txt in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)
