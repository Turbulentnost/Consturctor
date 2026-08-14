"""Web UI конструктора: статика + CORS-прокси к backend gateway."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8780"))
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:7812").rstrip("/")


def _path_only(raw: str) -> str:
    return raw.split("?", 1)[0]


def _query(raw: str) -> str:
    return ("?" + raw.split("?", 1)[1]) if "?" in raw else ""


class WebUiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        path = _path_only(self.path)
        if path.endswith((".html", ".js", ".css")) or path in {"/", ""}:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")
        self.end_headers()

    def do_GET(self) -> None:
        if self._maybe_proxy("GET"):
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self._maybe_proxy("POST"):
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        if self._maybe_proxy("PUT"):
            return
        self.send_error(404)

    def do_PATCH(self) -> None:
        if self._maybe_proxy("PATCH"):
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        if self._maybe_proxy("DELETE"):
            return
        self.send_error(404)

    def _maybe_proxy(self, method: str) -> bool:
        path = _path_only(self.path)
        if path == "/api/health":
            self._proxy("/health", method, "")
            return True
        if path.startswith("/api/gateway"):
            upstream = path[len("/api/gateway") :]
            self._proxy(upstream + _query(self.path), method, upstream)
            return True
        return False

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _proxy(self, upstream_path: str, method: str, _log_path: str) -> None:
        url = f"{GATEWAY}{upstream_path}"
        headers: dict[str, str] = {"Accept": "application/json"}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        content_type = self.headers.get("Content-Type")
        body = self._read_body() if method in {"POST", "PUT", "PATCH"} else None
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120.0) as resp:
                out = resp.read()
                code = resp.status
                resp_type = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            out = exc.read()
            code = exc.code
            resp_type = exc.headers.get("Content-Type", "application/json")
        except Exception as exc:
            out = json.dumps({"detail": str(exc)}, ensure_ascii=False).encode("utf-8")
            code = 502
            resp_type = "application/json; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", resp_type)
        self.end_headers()
        self.wfile.write(out)


def main() -> None:
    server = ThreadingHTTPServer((BIND_HOST, PORT), WebUiHandler)
    print(f"Constructor Web UI: http://127.0.0.1:{PORT}/")
    print(f"Backend proxy: {GATEWAY}")
    server.serve_forever()


if __name__ == "__main__":
    main()
