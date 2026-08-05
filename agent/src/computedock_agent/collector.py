from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType


MEBIBYTE = 1024 * 1024


class CollectionError(RuntimeError):
    """Raised when a complete GPU sample cannot be collected."""


@dataclass(frozen=True)
class GpuMetric:
    gpuid: str
    memory_used: int
    memory_total: int
    utilization: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "gpuid": self.gpuid,
            "memory_used": self.memory_used,
            "memory_total": self.memory_total,
            "utilization": self.utilization,
        }


class NvmlCollector:
    def __init__(
        self,
        nvml: ModuleType | object | None = None,
        *,
        disabled: bool = False,
    ) -> None:
        self._nvml = nvml
        self._disabled = disabled
        self._initialized = False

    @property
    def nvml(self) -> ModuleType | object:
        if self._nvml is None:
            try:
                self._nvml = importlib.import_module("pynvml")
            except Exception as exc:
                raise CollectionError(f"cannot import pynvml: {exc}") from exc
        return self._nvml

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            self.nvml.nvmlInit()
        except Exception as exc:
            raise CollectionError(f"cannot initialize NVML: {exc}") from exc
        self._initialized = True

    def _reject_mig(self, handle: object) -> None:
        get_mig_mode = getattr(self.nvml, "nvmlDeviceGetMigMode", None)
        if get_mig_mode is None:
            return
        try:
            current_mode, _pending_mode = get_mig_mode(handle)
        except Exception as exc:
            not_supported_type = getattr(self.nvml, "NVMLError_NotSupported", None)
            if not_supported_type is not None and isinstance(exc, not_supported_type):
                return
            raise
        enabled_value = getattr(self.nvml, "NVML_DEVICE_MIG_ENABLE", 1)
        if current_mode == enabled_value:
            raise CollectionError("MIG-enabled GPUs are not supported")

    def collect(self) -> list[GpuMetric]:
        if self._disabled:
            return []
        try:
            self._ensure_initialized()
            metrics: list[GpuMetric] = []
            for index in range(self.nvml.nvmlDeviceGetCount()):
                handle = self.nvml.nvmlDeviceGetHandleByIndex(index)
                self._reject_mig(handle)
                gpu_uuid = self.nvml.nvmlDeviceGetUUID(handle)
                if isinstance(gpu_uuid, bytes):
                    gpu_uuid = gpu_uuid.decode("utf-8")
                memory = self.nvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = self.nvml.nvmlDeviceGetUtilizationRates(handle)
                metrics.append(
                    GpuMetric(
                        gpuid=str(gpu_uuid),
                        memory_used=int(memory.used // MEBIBYTE),
                        memory_total=int(memory.total // MEBIBYTE),
                        utilization=int(utilization.gpu),
                    )
                )
            return metrics
        except CollectionError:
            self._reset_after_failure()
            raise
        except Exception as exc:
            self._reset_after_failure()
            raise CollectionError(f"cannot collect a complete GPU sample: {exc}") from exc

    def _reset_after_failure(self) -> None:
        if not self._initialized:
            return
        try:
            self.nvml.nvmlShutdown()
        except Exception:
            pass
        self._initialized = False

    def close(self) -> None:
        if not self._initialized:
            return
        try:
            self.nvml.nvmlShutdown()
        finally:
            self._initialized = False
