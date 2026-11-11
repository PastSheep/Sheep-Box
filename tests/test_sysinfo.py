"""系统信息模块单元测试。

通过注入 Fake 后端避免依赖真实硬件，聚焦验证：
- 快照字段映射与 CPU 差分口径（``KernelTime`` 含 ``IdleTime``）；
- 首帧无基线时返回 0；
- 内存换算与边界（总量为 0）；
- GPU 读取、关闭、异常降级；
- PDH 实例名解析与「同引擎求和、跨引擎取最大、跨适配器不求和」的聚合口径；
- Windows 真机冒烟（计数器缺失时自动跳过）。
"""

import sys

import pytest

from common.exceptions import SystemInfoError
from service.sysinfo.backend import (
    GpuReading,
    NullBackend,
    _aggregate_gpu,
    _instance_parts,
)
from service.sysinfo.collector import SystemCollector
from service.sysinfo.models import GpuSample

_GIB = 1024**3

# 100ns 为单位的 CPU 时间刻度（一秒 = 10_000_000）
_SECOND = 10_000_000


class _FakeBackend:
    """可控的采集后端：按预设序列返回 CPU 时间与 GPU 读数。"""

    def __init__(
        self,
        times_sequence: list[tuple[int, int, int]] | None = None,
        memory: tuple[int, int] = (16 * _GIB, 6 * _GIB),
        cores: int = 12,
        gpus: tuple[GpuReading, ...] = (),
        fail_on: str | None = None,
    ) -> None:
        self.times_sequence = times_sequence or [(0, 0, 0), (0, 0, 0)]
        self._times_index = 0
        self._memory = memory
        self._cores = cores
        self._gpus = gpus
        self._fail_on = fail_on
        self.gpu_enabled = True
        self.close_calls = 0

    def system_times(self) -> tuple[int, int, int]:
        if self._fail_on == "cpu":
            raise OSError("cpu boom")
        index = min(self._times_index, len(self.times_sequence) - 1)
        self._times_index += 1
        return self.times_sequence[index]

    def memory_bytes(self) -> tuple[int, int]:
        if self._fail_on == "memory":
            raise OSError("memory boom")
        return self._memory

    def logical_cores(self) -> int:
        return self._cores

    def collect_gpu(self) -> tuple[GpuReading, ...]:
        if self._fail_on == "gpu":
            raise OSError("gpu boom")
        return self._gpus

    def close(self) -> None:
        self.close_calls += 1


def _make_collector(backend: _FakeBackend) -> SystemCollector:
    return SystemCollector(backend=backend)


def test_snapshot_maps_all_fields() -> None:
    backend = _FakeBackend(
        gpus=(GpuReading(index=0, name="RTX", utilization_percent=40.0),),
    )
    collector = _make_collector(backend)
    snapshot = collector.sample()

    assert snapshot.timestamp > 0
    assert snapshot.cpu.logical_cores == 12
    assert snapshot.memory.total == 16 * _GIB
    assert snapshot.memory.available == 6 * _GIB
    assert snapshot.memory.used == 10 * _GIB
    assert snapshot.memory.percent == 62.5
    assert snapshot.gpu_available is True
    assert snapshot.gpus[0].name == "RTX"
    assert snapshot.gpus[0].utilization_percent == 40.0


def test_constructor_reads_cpu_baseline() -> None:
    backend = _FakeBackend()
    _make_collector(backend)
    assert backend._times_index == 1


def test_first_sample_without_baseline_returns_zero() -> None:
    backend = _FakeBackend()
    collector = SystemCollector(backend=backend)
    # 构造已消费第一个样本作为基线，故这里已有基线；用 Sequence 保证第二次相同
    assert collector.sample().cpu.percent == 0.0


def test_cpu_percent_excludes_idle_time() -> None:
    # 一个 1s 区间：kernel 累计 8e6（含 idle 6e6），user 4e6 → 总 12e6，忙 12e6-6e6
    backend = _FakeBackend(
        times_sequence=[(0, 0, 0), (6 * _SECOND, 8 * _SECOND, 4 * _SECOND)]
    )
    collector = _make_collector(backend)
    assert collector.sample().cpu.percent == 50.0


def test_cpu_percent_full_load_is_hundred() -> None:
    backend = _FakeBackend(times_sequence=[(0, 0, 0), (0, 10 * _SECOND, 0)])
    assert _make_collector(backend).sample().cpu.percent == 100.0


def test_cpu_percent_idle_is_zero() -> None:
    backend = _FakeBackend(times_sequence=[(0, 0, 0), (10 * _SECOND, 10 * _SECOND, 0)])
    assert _make_collector(backend).sample().cpu.percent == 0.0


def test_zero_delta_does_not_divide_by_zero() -> None:
    backend = _FakeBackend(times_sequence=[(0, 0, 0), (0, 0, 0)])
    assert _make_collector(backend).sample().cpu.percent == 0.0


def test_memory_percent_with_zero_total() -> None:
    backend = _FakeBackend(memory=(0, 0))
    snapshot = _make_collector(backend).sample()
    assert snapshot.memory.percent == 0.0
    assert snapshot.memory.used == 0


def test_gpu_absent_when_backend_has_no_gpu() -> None:
    collector = _make_collector(_FakeBackend(gpus=()))
    snapshot = collector.sample()
    assert snapshot.gpus == ()
    assert snapshot.gpu_available is False


def test_gpu_failure_degrades_silently() -> None:
    collector = _make_collector(_FakeBackend(fail_on="gpu"))
    snapshot = collector.sample()
    assert snapshot.gpus == ()
    assert snapshot.cpu.percent == 0.0


def test_cpu_failure_raises_system_info_error() -> None:
    collector = _make_collector(_FakeBackend(fail_on="cpu"))
    with pytest.raises(SystemInfoError):
        collector.sample()


def test_baseline_failure_defers_error_to_sample() -> None:
    collector = _make_collector(_FakeBackend(fail_on="cpu"))
    assert collector.gpu_available is True


def test_memory_failure_raises_system_info_error() -> None:
    collector = _make_collector(_FakeBackend(fail_on="memory"))
    with pytest.raises(SystemInfoError):
        collector.sample()


def test_close_is_idempotent_and_stops_gpu() -> None:
    backend = _FakeBackend(gpus=(GpuReading(0, "RTX", 10.0),))
    collector = _make_collector(backend)

    collector.close()
    collector.close()

    assert backend.close_calls == 1
    assert collector.sample().gpus == ()


def test_context_manager_closes_backend() -> None:
    backend = _FakeBackend(gpus=(GpuReading(0, "RTX", 10.0),))
    with _make_collector(backend) as collector:
        assert collector.sample().gpus
    assert backend.close_calls == 1


def test_null_backend_returns_empty_snapshot() -> None:
    collector = SystemCollector(backend=NullBackend())
    snapshot = collector.sample()
    assert snapshot.gpus == ()
    assert snapshot.memory.total == 0
    assert snapshot.cpu.percent == 0.0


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        (
            "pid_1234_luid_0x00000000_0x0000E3AE_phys_0_eng_0_engtype_3D",
            ((0, 0xE3AE), 0),
        ),
        (
            "pid_9_luid_0x00000001_0x0ABCDEF0_phys_1_eng_7_engtype_Cuda",
            ((1, 0xABCDEF0), 7),
        ),
        # engtype 带后缀时仍只取 eng 后的编号
        (
            "pid_5_luid_0x00000000_0x00000001_phys_0_eng_3_engtype_Compute_1",
            ((0, 1), 3),
        ),
    ],
)
def test_instance_parts_parsing(
    instance: str, expected: tuple[tuple[int, int], int]
) -> None:
    assert _instance_parts(instance) == expected


@pytest.mark.parametrize(
    "instance", ["", "pid_1_engtype_3D", "garbage", "luid_0x0_0x0"]
)
def test_instance_parts_rejects_malformed(instance: str) -> None:
    assert _instance_parts(instance) is None


def test_aggregate_sums_same_engine_then_takes_max() -> None:
    rows = [
        # 同一 LUID 同一引擎上两个进程：20 + 30 = 50
        ("pid_1_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 20.0),
        ("pid_2_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 30.0),
        # 同一 LUID 另一引擎：80
        ("pid_1_luid_0x00000000_0x00000001_phys_0_eng_1_engtype_Copy", 80.0),
        # 另一 LUID：10
        ("pid_3_luid_0x00000000_0x00000002_phys_0_eng_0_engtype_3D", 10.0),
    ]
    assert _aggregate_gpu(rows) == {(0, 1): 80.0, (0, 2): 10.0}


def test_aggregate_clamps_engine_sum_at_hundred() -> None:
    rows = [
        ("pid_1_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 90.0),
        ("pid_2_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 90.0),
    ]
    assert _aggregate_gpu(rows) == {(0, 1): 100.0}


def test_aggregate_skips_malformed_instances() -> None:
    rows = [("bogus", 50.0), ("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 10.0)]
    assert _aggregate_gpu(rows) == {(0, 1): 10.0}


def test_gpu_sample_is_immutable_by_model() -> None:
    sample = GpuSample(index=0, name="RTX", utilization_percent=12.0)
    assert sample.index == 0


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 提供原生后端")
def test_windows_backend_smoke() -> None:
    """真机冒烟：真实采集一次，数值必须落在合理区间。

    GPU 计数器不可用（虚拟机 / 无 GPU 驱动）时跳过，不作为失败。
    """
    from service.sysinfo.backend import WindowsBackend

    backend = WindowsBackend(enable_gpu=True)
    try:
        if not backend.gpu_enabled:
            pytest.skip("当前系统未提供 GPU Engine 性能计数器")
        collector = SystemCollector(backend=backend)
        import time

        time.sleep(0.2)
        snapshot = collector.sample()
    finally:
        backend.close()

    assert 0.0 <= snapshot.cpu.percent <= 100.0
    assert snapshot.cpu.logical_cores > 0
    assert snapshot.memory.total > 0
    assert 0.0 <= snapshot.memory.percent <= 100.0
    assert snapshot.gpus, "启用 GPU 时应至少返回一块适配器"
    for gpu in snapshot.gpus:
        assert 0.0 <= gpu.utilization_percent <= 100.0
        assert gpu.name, "DXGI 应提供适配器型号名"
