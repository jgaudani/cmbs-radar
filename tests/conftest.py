import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def ex102() -> bytes:
    s = fixture("cmbs_submission.txt")
    start = s.index(b"<?xml")
    end = s.index(b"</assetData>") + len(b"</assetData>")
    return s[start:end]


@pytest.fixture
def http_server():
    """Start a local server with a handler function(path, method) -> (status, body, headers)."""
    servers = []

    def start(route):
        class H(BaseHTTPRequestHandler):
            def _serve(self):
                status, body, headers = route(self)
                self.send_response(status)
                headers = headers or {}
                for k, v in headers.items():
                    self.send_header(k, v)
                if "Content-Length" not in headers:  # a test may promise more than it sends
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _serve

            def log_message(self, *_):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/"

    yield start
    for s in servers:
        s.shutdown()


@pytest.fixture
def test_dsn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    return dsn
