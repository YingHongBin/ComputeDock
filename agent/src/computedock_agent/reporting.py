from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


REQUEST_TIMEOUT_SECONDS = 10.0
RESPONSE_SUMMARY_LIMIT = 500


class ReportError(RuntimeError):
    """Raised when one reporting attempt fails."""


class HttpReporter:
    def __init__(
        self,
        server_url: str,
        token: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._server_url = server_url
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)

    def send(self, payload: dict[str, Any]) -> None:
        try:
            response = self._client.post(
                self._server_url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
        except Exception as exc:
            raise ReportError(f"HTTP request failed: {exc}") from exc
        if not 200 <= response.status_code < 300:
            summary = " ".join(response.text.split())[:RESPONSE_SUMMARY_LIMIT]
            message = f"HTTP {response.status_code}"
            if summary:
                message = f"{message}: {summary}"
            raise ReportError(message)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class JsonLinesReporter:
    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path

    def send(self, payload: dict[str, Any]) -> None:
        try:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            with self._output_path.open("a", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise ReportError(f"cannot append test output: {exc}") from exc

    def close(self) -> None:
        return None
