"""Static demo UI + CORS proxy for local platform health checks."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8790"))
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:7812").rstrip("/")

DOCKER_HEALTH_HOSTS = {
    "7812": "constructor-gateway",
    "7820": "platform-kpi",
    "7821": "platform-tool-imap",
    "7822": "platform-tool-onec",
    "7823": "platform-tool-shell",
    "7824": "platform-tool-browser",
    "7825": "platform-orchestrator-api",
    "7826": "host.docker.internal",
    "7827": "host.docker.internal",
    "7828": "host.docker.internal",
}


def _request_path(raw_path: str) -> str:
    return raw_path.split("?", 1)[0]


def _request_query(raw_path: str) -> str:
    if "?" not in raw_path:
        return ""
    return "?" + raw_path.split("?", 1)[1]


def health_host(port: str) -> str:
    env_key = f"HEALTH_HOST_{port}"
    if env_key in os.environ:
        return os.environ[env_key]
    if os.environ.get("DOCKER_NETWORK") == "1":
        return DOCKER_HEALTH_HOSTS.get(port, "127.0.0.1")
    return "127.0.0.1"


def health_url(port: str) -> str:
    return f"http://{health_host(port)}:{port}/health"


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        path = _request_path(self.path)
        if path.endswith((".html", ".js", ".css")) or path in {"/", ""}:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if path.startswith("/health/"):
            port = path.rsplit("/", 1)[-1]
            self._proxy_health(port)
            return
        if path == "/api/gateway-health":
            self._proxy_gateway_request("GET", "/health", "", None)
            return
        if path.startswith("/api/gateway/"):
            upstream = path[len("/api/gateway") :]
            self._proxy_gateway_request("GET", upstream, _request_query(self.path), None)
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = _request_path(self.path)
        if path == "/api/login":
            self._proxy_gateway_request(
                "POST",
                "/api/v1/auth/login",
                "",
                self._read_json_body(),
            )
            return
        if path.startswith("/api/gateway/"):
            upstream = path[len("/api/gateway") :]
            self._proxy_gateway_request(
                "POST",
                upstream,
                _request_query(self.path),
                self._read_json_body(),
            )
            return
        self.send_error(404, "not found")

    def _read_json_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _forward_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        content_type = self.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _proxy_gateway_request(
        self,
        method: str,
        path: str,
        query: str,
        payload: bytes | None,
    ) -> None:
        url = f"{GATEWAY}{path}{query}"
        req = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers=self._forward_headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                body = resp.read()
                code = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            code = exc.code
        except Exception as exc:
            body = json.dumps({"detail": str(exc)}, ensure_ascii=False).encode("utf-8")
            code = 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_health(self, port: str) -> None:
        if not port.isdigit():
            self.send_error(400, "invalid port")
            return
        url = health_url(port)
        try:
            with urllib.request.urlopen(url, timeout=2.5) as resp:
                body = resp.read()
                payload = json.loads(body.decode("utf-8"))
                out = {"reachable": True, "port": int(port), "body": payload}
                code = 200
        except Exception as exc:
            out = {"reachable": False, "port": int(port), "error": str(exc)}
            code = 200
        data = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer((BIND_HOST, PORT), DemoHandler)
    print(f"Demo UI: http://127.0.0.1:{PORT}/")
    print(f"Gateway proxy target: {GATEWAY}")
    print(f"Bind: {BIND_HOST}:{PORT}")
    print("Press Ctrl+C to stop")
    server.serve_forever()


if __name__ == "__main__":
    main()
