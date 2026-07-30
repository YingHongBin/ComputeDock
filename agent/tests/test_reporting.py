from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from computedock_agent.reporting import HttpReporter, JsonLinesReporter, ReportError


class ReportingTests(unittest.TestCase):
    def test_http_reporter_posts_to_the_exact_url_with_bearer_token(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        client = httpx.Client(
            transport=httpx.MockTransport(handler), timeout=10.0
        )
        reporter = HttpReporter(
            "http://example.invalid/complete/data/path?source=x", "secret", client
        )
        payload = {"container_name": "worker", "gpus": []}
        reporter.send(payload)

        self.assertEqual(len(seen), 1)
        self.assertEqual(
            str(seen[0].url), "http://example.invalid/complete/data/path?source=x"
        )
        self.assertEqual(seen[0].headers["authorization"], "Bearer secret")
        self.assertEqual(json.loads(seen[0].content), payload)
        self.assertEqual(seen[0].extensions["timeout"]["read"], 10.0)

    def test_non_2xx_response_raises_once_with_a_bounded_summary(self) -> None:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, text="temporarily unavailable")

        reporter = HttpReporter(
            "http://example.invalid/report",
            "token",
            httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with self.assertRaisesRegex(ReportError, "HTTP 503"):
            reporter.send({})
        self.assertEqual(calls, 1)

    def test_json_lines_reporter_appends_and_flushes_complete_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "samples.jsonl"
            reporter = JsonLinesReporter(output)
            reporter.send({"sequence": 1, "name": "容器"})
            reporter.send({"sequence": 2})
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [json.loads(line) for line in lines],
                [{"sequence": 1, "name": "容器"}, {"sequence": 2}],
            )


if __name__ == "__main__":
    unittest.main()
