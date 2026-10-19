"""Run one loopback server for any number of form sessions (stdlib only)."""
import argparse
import json
import secrets
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import Conflict, Store

ROOT = Path(__file__).resolve().parent
MAX_BODY = 2 * 1024 * 1024


def make_server(root=ROOT, port=8765):
    store = Store(root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Do not log contact data or capability tokens.

        def reply(self, value, status=200, content_type="application/json; charset=utf-8"):
            body = json.dumps(value, allow_nan=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def route(self, method):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                return self.reply({"error": "Invalid host"}, 403)
            parsed = urlsplit(self.path)
            parts = parsed.path.strip("/").split("/")
            if method == "GET" and parts == ["health"]:
                return self.reply({"service": "pai-forms", "version": 1})
            if parts[0] == "api":
                if self.headers.get("X-Forms-Token") != token:
                    return self.reply({"error": "Invalid session token"}, 403)
                if method == "POST":
                    if self.headers.get("Origin") != f"http://{host}":
                        return self.reply({"error": "Invalid origin"}, 403)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY:
                        return self.reply({"error": "Request body must be 1 byte to 2 MiB"}, 413)
                    if self.headers.get_content_type() != "application/json":
                        return self.reply({"error": "Expected application/json"}, 415)
                    def invalid_constant(value):
                        raise ValueError("Non-finite JSON is not supported")
                    body = json.loads(self.rfile.read(length), parse_constant=invalid_constant)
                    if not isinstance(body, dict):
                        raise ValueError("Request must be an object")
                if method == "POST" and parts == ["api", "sessions"]:
                    return self.reply(store.create(body.get("form"), body.get("raw_input", ""), body.get("initial_data", {})), 201)
                if len(parts) in (4, 5) and parts[1] == "sessions":
                    name, execution_id = parts[2:4]
                    if method == "GET" and len(parts) == 4:
                        return self.reply(store.read(name, execution_id))
                    if method == "POST" and parts[4:] == ["actions"]:
                        return self.reply(store.action(name, execution_id, body))
                    if method == "GET" and parts[4:] == ["snapshot"]:
                        revision = int(parse_qs(parsed.query).get("revision", ["0"])[0])
                        return self.reply(store.snapshot(name, execution_id, revision))
                return self.reply({"error": "Unknown endpoint"}, 404)
            if method != "GET":
                return self.reply({"error": "Unknown endpoint"}, 404)
            if parts == ["runtime", "config.json"]:
                return self.reply({"token": token})
            if len(parts) == 2 and parts[0] == "runtime" and parts[1] in ("runtime.js", "runtime.css"):
                suffix = "javascript" if parts[1].endswith(".js") else "css"
                return self.reply((ROOT / "runtime" / parts[1]).read_bytes(), content_type=f"text/{suffix}; charset=utf-8")
            if len(parts) == 3 and parts[0] == "assets" and parts[2] in ("form.js", "form.css"):
                folder = store.form(parts[1])
                suffix = "javascript" if parts[2].endswith(".js") else "css"
                return self.reply((folder / parts[2]).read_bytes(), content_type=f"text/{suffix}; charset=utf-8")
            if (len(parts) == 2 and parts[0] == "new") or (len(parts) == 3 and parts[0] == "session"):
                folder = store.form(parts[1])
                if parts[0] == "session":
                    store.read(parts[1], parts[2])
                return self.reply((folder / "form.html").read_bytes(), content_type="text/html; charset=utf-8")
            return self.reply({"error": "Open /new/form-<name> to start a form"}, 404)

        def dispatch(self, method):
            try:
                self.route(method)
            except Conflict as exc:
                self.reply({"error": str(exc)}, 409)
            except FileNotFoundError:
                self.reply({"error": "Session or resource not found"}, 404)
            except (ValueError, TypeError, KeyError) as exc:
                self.reply({"error": str(exc)}, 400)
            except OSError:
                self.reply({"error": "Storage failed; retry the same action to recover"}, 500)

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        store.recover_logs()
    except Exception:
        server.server_close()
        raise
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--form", default="form-contact")
    parser.add_argument("--migrate", action="store_true", help="Migrate legacy metadata into output files with the server stopped, then exit")
    args = parser.parse_args()
    if args.migrate:
        print(f"Migrated {Store(ROOT).migrate()} sessions into output files.")
        return
    Store(ROOT).form(args.form)
    base = f"http://127.0.0.1:{args.port}"
    try:
        server = make_server(port=args.port)
    except OSError:
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as response:
                health = json.load(response)
            if health != {"service": "pai-forms", "version": 1}:
                raise ValueError("Unrecognized server")
        except (OSError, ValueError) as exc:
            parser.error(f"Port unavailable and no compatible forms runner found: {exc}")
        print(f"Reusing running server. Open {base}/new/{args.form}", flush=True)
        return
    print(f"Open {base}/new/{args.form}\nKeep this process running; Ctrl-C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
