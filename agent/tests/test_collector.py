from __future__ import annotations

import unittest
from types import SimpleNamespace

from computedock_agent.collector import CollectionError, NvmlCollector


class FakeNotSupported(Exception):
    pass


class FakeNvml:
    NVML_DEVICE_MIG_ENABLE = 1
    NVMLError_NotSupported = FakeNotSupported

    def __init__(self, *, count: int = 1, mig: bool = False, fail_memory: bool = False):
        self.count = count
        self.mig = mig
        self.fail_memory = fail_memory
        self.init_calls = 0
        self.shutdown_calls = 0

    def nvmlInit(self) -> None:
        self.init_calls += 1

    def nvmlShutdown(self) -> None:
        self.shutdown_calls += 1

    def nvmlDeviceGetCount(self) -> int:
        return self.count

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        return index

    def nvmlDeviceGetMigMode(self, _handle: int) -> tuple[int, int]:
        return (1 if self.mig else 0, 1 if self.mig else 0)

    def nvmlDeviceGetUUID(self, index: int) -> bytes:
        return f"GPU-uuid-{index}".encode()

    def nvmlDeviceGetMemoryInfo(self, _handle: int) -> SimpleNamespace:
        if self.fail_memory:
            raise RuntimeError("memory query failed")
        return SimpleNamespace(used=2 * 1024**3, total=24 * 1024**3)

    def nvmlDeviceGetUtilizationRates(self, _handle: int) -> SimpleNamespace:
        return SimpleNamespace(gpu=37)


class CollectorTests(unittest.TestCase):
    def test_collects_uuid_memory_mib_and_gpu_utilization(self) -> None:
        nvml = FakeNvml(count=2)
        collector = NvmlCollector(nvml)
        metrics = collector.collect()
        self.assertEqual(
            [metric.as_dict() for metric in metrics],
            [
                {
                    "gpuid": "GPU-uuid-0",
                    "memory_used": 2048,
                    "memory_total": 24576,
                    "utilization": 37,
                },
                {
                    "gpuid": "GPU-uuid-1",
                    "memory_used": 2048,
                    "memory_total": 24576,
                    "utilization": 37,
                },
            ],
        )
        collector.close()
        self.assertEqual(nvml.shutdown_calls, 1)

    def test_no_visible_gpu_returns_empty_batch(self) -> None:
        collector = NvmlCollector(FakeNvml(count=0))
        self.assertEqual(collector.collect(), [])

    def test_disabled_collection_does_not_initialize_nvml(self) -> None:
        nvml = FakeNvml()
        collector = NvmlCollector(nvml, disabled=True)
        self.assertEqual(collector.collect(), [])
        collector.close()
        self.assertEqual(nvml.init_calls, 0)
        self.assertEqual(nvml.shutdown_calls, 0)

    def test_mig_gpu_rejects_the_entire_batch(self) -> None:
        nvml = FakeNvml(mig=True)
        with self.assertRaisesRegex(CollectionError, "MIG"):
            NvmlCollector(nvml).collect()
        self.assertEqual(nvml.shutdown_calls, 1)

    def test_single_gpu_failure_rejects_the_entire_batch_and_reinitializes(self) -> None:
        nvml = FakeNvml(fail_memory=True)
        collector = NvmlCollector(nvml)
        with self.assertRaises(CollectionError):
            collector.collect()
        self.assertEqual(nvml.shutdown_calls, 1)
        nvml.fail_memory = False
        self.assertEqual(len(collector.collect()), 1)
        self.assertEqual(nvml.init_calls, 2)


if __name__ == "__main__":
    unittest.main()
