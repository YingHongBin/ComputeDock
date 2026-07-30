from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from computedock_agent.reporting import HttpReporter


class RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        self.server.received = {  # type: ignore[attr-defined]
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "payload": json.loads(body),
        }
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, _format: str, *args: Any) -> None:
        return None


class HttpIntegrationTests(unittest.TestCase):
    def test_real_local_http_server_receives_one_complete_batch(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        payload = {
            "container_name": "worker",
            "collected_at": "2026-07-29T10:30:00.000Z",
            "gpus": [
                {
                    "gpuid": "GPU-one",
                    "memory_used": 1024,
                    "memory_total": 24576,
                    "utilization": 50,
                }
            ],
        }
        try:
            # Keep this integration test independent from the developer machine's
            # optional HTTP proxy configuration.
            with patch.dict(
                os.environ,
                {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"},
            ):
                reporter = HttpReporter(
                    f"http://127.0.0.1:{server.server_port}/full/report/path",
                    "resource-token",
                )
                try:
                    reporter.send(payload)
                finally:
                    reporter.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(
            server.received,  # type: ignore[attr-defined]
            {
                "path": "/full/report/path",
                "authorization": "Bearer resource-token",
                "payload": payload,
            },
        )


if __name__ == "__main__":
    unittest.main()
