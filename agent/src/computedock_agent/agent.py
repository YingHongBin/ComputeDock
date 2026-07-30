from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .collector import GpuMetric


class Collector(Protocol):
    def collect(self) -> list[GpuMetric]: ...

    def close(self) -> None: ...


class Reporter(Protocol):
    def send(self, payload: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def build_payload(
    container_name: str,
    collected_at: str,
    metrics: list[GpuMetric],
) -> dict[str, Any]:
    return {
        "container_name": container_name,
        "collected_at": collected_at,
        "gpus": [metric.as_dict() for metric in metrics],
    }


def next_collection_deadline(
    previous_deadline: float,
    interval: int,
    now: float,
) -> float:
    candidate = previous_deadline + interval
    if candidate < now:
        skipped_intervals = math.ceil((now - candidate) / interval)
        candidate += skipped_intervals * interval
    return candidate


def _safe_error_message(exc: Exception, secret: str | None) -> str:
    message = str(exc)
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return message


class Agent:
    def __init__(
        self,
        container_name: str,
        interval: int,
        collector: Collector,
        reporter: Reporter,
        stop_event: threading.Event,
        token: str | None,
        logger: logging.Logger,
        monotonic: Callable[[], float] = time.monotonic,
        timestamp: Callable[[], str] = utc_timestamp,
    ) -> None:
        self._container_name = container_name
        self._interval = interval
        self._collector = collector
        self._reporter = reporter
        self._stop_event = stop_event
        self._token = token
        self._logger = logger
        self._monotonic = monotonic
        self._timestamp = timestamp

    def _log_exception(self, stage: str, exc: Exception) -> None:
        self._logger.error(
            "stage=%s container=%r error=%s",
            stage,
            self._container_name,
            _safe_error_message(exc, self._token),
        )

    def collect_and_report_once(self) -> None:
        collected_at = self._timestamp()
        try:
            metrics = self._collector.collect()
        except Exception as exc:
            self._log_exception("nvml_collection", exc)
            return
        if not metrics:
            return
        payload = build_payload(self._container_name, collected_at, metrics)
        try:
            self._reporter.send(payload)
        except Exception as exc:
            self._log_exception("reporting", exc)

    def run(self) -> None:
        deadline = self._monotonic()
        try:
            while not self._stop_event.is_set():
                self.collect_and_report_once()
                now = self._monotonic()
                deadline = next_collection_deadline(deadline, self._interval, now)
                self._stop_event.wait(max(0.0, deadline - now))
        finally:
            for stage, closeable in (
                ("reporter_close", self._reporter),
                ("nvml_close", self._collector),
            ):
                try:
                    closeable.close()
                except Exception as exc:
                    self._log_exception(stage, exc)
