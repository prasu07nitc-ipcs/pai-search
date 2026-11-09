"""Bounded, DNS-pinned HTTP(S) fetches for webpage tools."""

import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import quote, urldefrag, urljoin, urlsplit


# Identity encoding avoids decompression beyond the 2-MiB body cap.
# Socket deadlines bound individual operations; blocking DNS additionally needs
# the runner process timeout (default 20s, configurable up to 300s).
_LIMIT = 2 * 1024 * 1024
_SECONDS = 15.0


class WebpageError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebpageError("timeout", "The page could not be fetched within 15 seconds.")
    return remaining


def validate_url(url: str):
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
        raise WebpageError("invalid_url", "Provide a valid absolute HTTP(S) URL without credentials.") from None


def _addresses(host: str, port: int):
    # Reject a mixed public/private DNS answer, then pin the first validated IP.
    # This prevents later connection-time DNS resolution from changing the target.
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise WebpageError("dns_error", "The hostname could not be resolved.") from None
    if not addresses:
        raise WebpageError("dns_error", "The hostname returned no addresses.")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or ip.is_multicast or (mapped and not mapped.is_global):
            raise WebpageError("blocked_address", "The URL resolves to a non-public address.")
    return addresses[0]


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, tls_context, deadline):
        super().__init__(host, port, timeout=_remaining(deadline))
        self.address = address
        self.tls_context = tls_context
        self.deadline = deadline

    def connect(self):
        family, kind, protocol, _, address = self.address
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(_remaining(self.deadline))
            sock.connect(address)
            if self.tls_context is not None:
                sock.settimeout(_remaining(self.deadline))
                sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except BaseException:
            sock.close()
            raise


def download_html(url: str) -> dict:
    """Fetch an absolute public HTTP(S) URL and return HTML or a structured error.

    No optional inputs. Uses a 15-second cooperative network budget, five redirects,
    and a 2-MiB body limit. A runner-enforced process timeout must also bound DNS.
    """
    result = {"final_url": None, "status": "error", "error": None}
    deadline = time.monotonic() + _SECONDS
    tls_context = None
    try:
        if not isinstance(url, str):
            raise WebpageError("invalid_url", "URL must be a string.")
        current = urldefrag(url)[0]
        if current != url:
            validate_url(url)
        visited: set[str] = set()
        for hop in range(6):
            if current in visited:
                raise WebpageError("redirect_error", "A redirect loop was detected.")
            visited.add(current)
            parts, host, port = validate_url(current)
            address = _addresses(host, port)
            _remaining(deadline)
            secure = parts.scheme == "https"
            if secure and tls_context is None:
                tls_context = ssl.create_default_context()
            connection = _PinnedConnection(host, port, address, tls_context if secure else None, deadline)
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
                            raise WebpageError("redirect_error", "Redirect location missing or five-redirect limit exceeded.")
                        current = urldefrag(urljoin(current, location))[0]
                        continue
                    if not 200 <= response.status < 300:
                        raise WebpageError("http_error", f"The server returned HTTP {response.status}.")
                    if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
                        raise WebpageError("unsupported_content_type", "The response is not HTML.")
                    if response.getheader("Content-Encoding", "identity").strip().lower() != "identity":
                        raise WebpageError("unsupported_encoding", "The server returned compressed content despite an identity request.")
                    if response.length is not None and response.length > _LIMIT:
                        raise WebpageError("response_too_large", "The HTML response exceeds 2 MiB.")
                    chunks = bytearray()
                    while True:
                        # The response retains its socket even if HTTPConnection detaches it.
                        remaining = _remaining(deadline)
                        network_socket.settimeout(remaining)
                        block = response.read1(min(65536, _LIMIT + 1 - len(chunks)))
                        _remaining(deadline)
                        if not block:
                            if response.length not in (None, 0):
                                raise WebpageError("network_error", "The response body ended prematurely.")
                            break
                        chunks.extend(block)
                        if len(chunks) > _LIMIT:
                            raise WebpageError("response_too_large", "The HTML response exceeds 2 MiB.")
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
    except WebpageError as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    except (TimeoutError, socket.timeout):
        result["error"] = {"code": "timeout", "message": "The page could not be fetched within the time limit."}
    except ssl.SSLError:
        result["error"] = {"code": "tls_error", "message": "A secure connection could not be established."}
    except (OSError, http.client.HTTPException):
        result["error"] = {"code": "network_error", "message": "The HTTP request failed or the response was invalid."}
    return result
