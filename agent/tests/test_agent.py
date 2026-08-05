from __future__ import annotations

import io
import logging
import signal
import threading
import unittest
from unittest.mock import patch

from computedock_agent.agent import Agent, build_payload, next_collection_deadline
from computedock_agent.cli import gpu_collection_is_disabled, install_signal_handlers
from computedock_agent.collector import GpuMetric


class FakeCollector:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = [] if result is None else result
        self.error = error
        self.closed = False

    def collect(self):
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True


class FakeReporter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.payloads = []
        self.closed = False

    def send(self, payload) -> None:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True


def test_logger() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.Logger("test-agent", level=logging.ERROR)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, stream


class AgentTests(unittest.TestCase):
    def make_agent(self, collector, reporter, logger):
        return Agent(
            container_name="worker",
            interval=15,
            collector=collector,
            reporter=reporter,
            stop_event=threading.Event(),
            token="top-secret",
            logger=logger,
            timestamp=lambda: "2026-07-29T10:30:00.000Z",
        )

    def test_payload_contains_only_the_agreed_fields(self) -> None:
        payload = build_payload(
            "worker",
            "2026-07-29T10:30:00.000Z",
            [GpuMetric("GPU-one", 1, 2, 3)],
        )
        self.assertEqual(
            payload,
            {
                "container_name": "worker",
                "collected_at": "2026-07-29T10:30:00.000Z",
                "gpus": [
                    {
                        "gpuid": "GPU-one",
                        "memory_used": 1,
                        "memory_total": 2,
                        "utilization": 3,
                    }
                ],
            },
        )

    def test_empty_gpu_list_is_not_reported_or_logged(self) -> None:
        logger, stream = test_logger()
        reporter = FakeReporter()
        self.make_agent(FakeCollector([]), reporter, logger).collect_and_report_once()
        self.assertEqual(reporter.payloads, [])
        self.assertEqual(stream.getvalue(), "")

    def test_collection_failure_is_logged_and_not_reported(self) -> None:
        logger, stream = test_logger()
        reporter = FakeReporter()
        self.make_agent(
            FakeCollector(error=RuntimeError("driver unavailable")), reporter, logger
        ).collect_and_report_once()
        self.assertEqual(reporter.payloads, [])
        self.assertIn("stage=nvml_collection", stream.getvalue())

    def test_reporting_failure_is_discarded_and_token_is_redacted(self) -> None:
        logger, stream = test_logger()
        reporter = FakeReporter(RuntimeError("rejected top-secret"))
        metric = GpuMetric("GPU-one", 1, 2, 3)
        self.make_agent(FakeCollector([metric]), reporter, logger).collect_and_report_once()
        self.assertEqual(len(reporter.payloads), 1)
        self.assertIn("[REDACTED]", stream.getvalue())
        self.assertNotIn("top-secret", stream.getvalue())

    def test_next_deadline_skips_missed_intervals_without_drift(self) -> None:
        self.assertEqual(next_collection_deadline(0.0, 15, 8.0), 15.0)
        self.assertEqual(next_collection_deadline(0.0, 15, 15.0), 15.0)
        self.assertEqual(next_collection_deadline(0.0, 15, 20.0), 30.0)
        self.assertEqual(next_collection_deadline(0.0, 15, 36.0), 45.0)

    def test_signal_handlers_request_a_graceful_stop(self) -> None:
        event = threading.Event()
        callbacks = {}

        def capture(sig, callback):
            callbacks[sig] = callback

        with patch("computedock_agent.cli.signal.signal", side_effect=capture):
            install_signal_handlers(event)
        callbacks[signal.SIGTERM](signal.SIGTERM, None)
        self.assertTrue(event.is_set())

    def test_gpu_collection_is_disabled_only_for_explicit_empty_modes(self) -> None:
        for value in ("void", " VOID ", "none", ""):
            with self.subTest(value=value):
                self.assertTrue(
                    gpu_collection_is_disabled({"NVIDIA_VISIBLE_DEVICES": value})
                )
        for environment in ({}, {"NVIDIA_VISIBLE_DEVICES": "all"}, {"NVIDIA_VISIBLE_DEVICES": "0,1"}):
            with self.subTest(environment=environment):
                self.assertFalse(gpu_collection_is_disabled(environment))


if __name__ == "__main__":
    unittest.main()
