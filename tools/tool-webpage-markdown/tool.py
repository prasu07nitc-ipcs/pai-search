"""Extract reader-style Markdown from a public webpage with Trafilatura.

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

Select --tool tool-webpage-markdown --timeout 60, especially for compare mode.
Requires Python 3.11+ and Trafilatura >=2.0,<3.0 in tools/.venv. The dependency
check follows argument validation and precedes downloading; it never installs.
"""

from __future__ import annotations

import http.client
import ipaddress
import os
from pathlib import Path
import re
import socket
import ssl
import time
import uuid
from typing import Literal
from urllib.parse import quote, urldefrag, urljoin, urlsplit


# Identity encoding avoids decompression beyond the 2-MiB body cap.
# Socket deadlines bound individual operations; blocking DNS additionally needs
# the runner process timeout (default 20s, configurable up to 300s).
_LIMIT = 2 * 1024 * 1024
_SECONDS = 15.0


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


def _download(url: str) -> dict:
    """Fetch an absolute public HTTP(S) URL and return HTML or a structured error.

    No optional inputs. Uses a 15-second cooperative network budget, five redirects,
    and a 2-MiB body limit. A runner-enforced process timeout must also bound DNS.
    """
    result = {"final_url": None, "status": "error", "error": None}
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
                    result.update(status="ok", html=html)
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


def _extract_markdown(
    url: str,
    mode: Literal["balanced", "precision", "recall", "compare"] = "balanced",
    include_images: Literal[False] = False,
    include_links: Literal[False] = False,
    include_tables: bool = True,
) -> dict:
    """Extract a public URL as Markdown, optionally comparing three modes.

    URL: absolute HTTP(S), <=8192 characters, without credentials or whitespace.
    Defaults retain tables and formatting, exclude images, links, and comments,
    enable backup extraction and disable deduplication. Requires Trafilatura 2.x.
    Network budget: 15 seconds; response limit: 2 MiB; runner timeout: 60 seconds.
    Saves UTF-8 Markdown directly in tool-local output/<run_id>.md. Compare joins
    nonempty variants with labeled headings; single modes preserve extracted text.
    Supported Markdown structure is retained; exact CSS/font layout is not.
    Expected failures return structured errors; unexpected exceptions propagate.
    """
    result = {"status": "error", "error": None, "requested_url": url,
              "final_url": None, "mode": mode}
    try:
        _validate(url)
        if mode not in ("balanced", "precision", "recall", "compare"):
            raise _Failure("invalid_options", "Unsupported extraction mode.")
        if any(type(flag) is not bool for flag in (include_images, include_links, include_tables)):
            raise _Failure("invalid_options", "Inclusion options must be booleans.")
        if include_images is not False or include_links is not False:
            raise _Failure("invalid_options", "Images and links must be disabled.")
        try:
            from importlib.metadata import version
            from trafilatura import extract
            if int(version("trafilatura").split(".")[0]) != 2:
                raise _Failure("incompatible_dependency", "Requires Trafilatura >=2.0,<3.0.")
        except ImportError:
            raise _Failure("missing_dependency", "Trafilatura or a required dependency is absent from the project environment.") from None
        downloaded = _download(url)
        result["final_url"] = downloaded["final_url"]
        if downloaded["status"] == "error":
            result["error"] = downloaded["error"]
            return result
        modes = ("balanced", "precision", "recall") if mode == "compare" else (mode,)
        variants = {}
        for selected in modes:
            markdown = extract(
                downloaded["html"], url=downloaded["final_url"],
                output_format="markdown", include_formatting=True,
                include_comments=False, include_images=False,
                include_links=False, include_tables=include_tables,
                fast=False, favor_precision=selected == "precision",
                favor_recall=selected == "recall", deduplicate=False,
                with_metadata=False, only_with_metadata=False,
            )
            variants[selected] = markdown.strip() if markdown and markdown.strip() else None
        if not any(variants.values()):
            raise _Failure("extraction_empty", "No main content could be extracted from the HTML.")
        if mode == "compare":
            content = "\n\n".join(f"# {selected}\n\n{variants[selected]}"
                                    for selected in modes if variants[selected] is not None)
        else:
            content = variants[mode]
        result.update(status="ok", result_file=_write_output(content))
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str) -> str:
    """Atomically replace <run_id>.md using a pinned tool-local directory."""
    # Runner-supplied IDs allow SHA-256 production inputs and UUID test runs.
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    run_id = os.environ.get("PROJECT_TOOL_RUN_ID", "")
    if re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", run_id) is None:
        raise _Failure("output_write_error", "Runner execution run_id is missing or invalid.")
    filename = f"{run_id}.md"
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
        raise _Failure("output_write_error", "Could not save <run_id>.md in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)


def extract_markdown(
    url: str,
    raw_input: str,
    mode: Literal["balanced", "precision", "recall", "compare"] = "balanced",
    include_images: Literal[False] = False,
    include_links: Literal[False] = False,
    include_tables: bool = True,
) -> dict:
    """Extract Markdown and save it directly to output/<run_id>.md.

    raw_input is the caller's original request, required and never interpreted.
    URL/options constraints match _extract_markdown; defaults are recorded in
    input.processed_input. Expected failures return output=null; successful paths
    are relative to tools/. Success atomically replaces the previous <run_id>.md.
    """
    processed = {"url": url, "mode": mode, "include_images": include_images,
                 "include_links": include_links, "include_tables": include_tables}
    payload = _extract_markdown(url, mode, include_images, include_links, include_tables)
    return {"input": {"raw_input": raw_input, "processed_input": processed},
            "output": payload.get("result_file"), "output_format": "markdown", "status": payload["status"],
            "error": payload["error"],
            "meta_data": {"requested_url": url, "final_url": payload["final_url"], "mode": mode}}
