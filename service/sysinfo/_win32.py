"""Windows 系统指标的原生 API 绑定（ctypes）。

只做「调系统 DLL + 拆结构体」，返回裸元组 / 列表，不含任何业务语义；把返回值
整理成数据模型的职责在 :mod:`service.sysinfo.backend`。

覆盖三项能力，全部零第三方依赖：

- **CPU**：``kernel32.GetSystemTimes`` —— 累计的 Idle / Kernel / User（100ns）；
  注意 ``KernelTime`` 已包含 ``IdleTime``，计算占用时必须减掉（否则读数虚高）；
- **内存**：``kernel32.GlobalMemoryStatusEx``；
- **GPU**：``pdh.dll`` 的 ``\\GPU Engine(*)\\Utilization Percentage``（WDDM 上报的
  引擎忙闲），以及 ``dxgi.dll`` 的适配器目录（用于排除虚拟/软件适配器、取型号名）。

本模块仅支持 Windows；非 Windows 平台在导入时即报错，由上层按平台判断后惰性导入。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from dataclasses import dataclass

if sys.platform != "win32":  # pragma: no cover - 仅 Windows 部署
    raise ImportError("service.sysinfo._win32 仅支持 Windows")

__all__ = [
    "AdapterInfo",
    "GpuEngineQuery",
    "NativeApiError",
    "list_adapters",
    "logical_processor_count",
    "memory_bytes",
    "system_times",
]

# --------------------------------------------------------------------------
# 错误与常量
# --------------------------------------------------------------------------


class NativeApiError(RuntimeError):
    """底层 Win32 / PDH / DXGI 调用失败。"""


_PDH_FMT_DOUBLE = 0x00000200
# PDH_STATUS 的 restype 是有符号 c_long，0x800007D2 需按有符号值比较
_PDH_MORE_DATA = ctypes.c_long(0x800007D2).value
_PDH_CSTATUS_NO_OBJECT = ctypes.c_long(0xC0000BB8).value

_HRESULT_OK = 0
_DXGI_ERROR_NOT_FOUND = ctypes.c_long(0x887A0002).value

_GPU_ENGINE_COUNTER = r"\GPU Engine(*)\Utilization Percentage"


def _status_text(status: int) -> str:
    """把有符号状态码格式化成便于排查的无符号十六进制。"""
    return f"0x{status & 0xFFFFFFFF:08X}"


# --------------------------------------------------------------------------
# PDH：GPU 引擎利用率
# --------------------------------------------------------------------------


class _PdhFmtCounterValue(ctypes.Structure):
    """``PDH_FMT_COUNTERVALUE``：状态码 + double 取值。"""

    _fields_ = [("CStatus", wt.DWORD), ("doubleValue", ctypes.c_double)]


class _PdhFmtCounterValueItem(ctypes.Structure):
    """``PDH_FMT_COUNTERVALUE_ITEM_W``：实例名 + 取值。"""

    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PdhFmtCounterValue)]


_pdh = ctypes.WinDLL("pdh")
_pdh.PdhOpenQueryW.argtypes = [
    ctypes.c_wchar_p,
    wt.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
_pdh.PdhOpenQueryW.restype = ctypes.c_long
_pdh.PdhAddEnglishCounterW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    wt.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
_pdh.PdhAddEnglishCounterW.restype = ctypes.c_long
_pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
_pdh.PdhCollectQueryData.restype = ctypes.c_long
_pdh.PdhGetFormattedCounterArrayW.argtypes = [
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    ctypes.POINTER(wt.DWORD),
    ctypes.POINTER(_PdhFmtCounterValueItem),
]
_pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_long
_pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
_pdh.PdhCloseQuery.restype = ctypes.c_long


class GpuEngineQuery:
    """持久 PDH 查询：全部 GPU 引擎实例的利用率。

    利用率属于 rate 计数器，需两次采集才有意义：构造时建立基线，之后每次
    :meth:`sample` 读到的值是「距上一次采集」的区间平均值——与
    ``psutil.cpu_percent(interval=None)`` 的语义相同，调用间隔越短越不稳定。

    Raises:
        NativeApiError: 打开查询或挂载计数器失败（该系统/驱动未暴露 GPU 计数器）。
    """

    def __init__(self) -> None:
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        status = _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query))
        if status != _HRESULT_OK:
            raise NativeApiError(f"PdhOpenQueryW 失败: {_status_text(status)}")
        try:
            status = _pdh.PdhAddEnglishCounterW(
                self._query,
                _GPU_ENGINE_COUNTER,
                0,
                ctypes.byref(self._counter),
            )
        except BaseException:
            self.close()
            raise
        if status != _HRESULT_OK:
            self.close()
            if status == _PDH_CSTATUS_NO_OBJECT:
                raise NativeApiError("系统未提供 GPU Engine 性能计数器")
            raise NativeApiError(f"PdhAddEnglishCounterW 失败: {_status_text(status)}")
        # 基线：第一次采集不取值，仅用于让后续差分有起点
        status = _pdh.PdhCollectQueryData(self._query)
        if status != _HRESULT_OK:
            self.close()
            raise NativeApiError(f"PdhCollectQueryData 失败: {_status_text(status)}")

    def sample(self) -> list[tuple[str, float]]:
        """采集一帧，返回 ``[(实例名, 利用率百分比), ...]``。

        Returns:
            有效实例的原始列表；读取失败的实例被跳过。

        Raises:
            NativeApiError: 采集或读取整批计数器失败。
        """
        status = _pdh.PdhCollectQueryData(self._query)
        if status != _HRESULT_OK:
            raise NativeApiError(f"PdhCollectQueryData 失败: {_status_text(status)}")

        size = wt.DWORD(0)
        count = wt.DWORD(0)
        status = _pdh.PdhGetFormattedCounterArrayW(
            self._counter,
            _PDH_FMT_DOUBLE,
            ctypes.byref(size),
            ctypes.byref(count),
            None,
        )
        if status != _PDH_MORE_DATA:
            raise NativeApiError(
                f"PdhGetFormattedCounterArrayW 探测失败: {_status_text(status)}"
            )
        # 实例可能在两次调用之间增减，缓冲按返回大小分配即可
        buffer = ctypes.create_string_buffer(size.value)
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhFmtCounterValueItem))
        status = _pdh.PdhGetFormattedCounterArrayW(
            self._counter,
            _PDH_FMT_DOUBLE,
            ctypes.byref(size),
            ctypes.byref(count),
            items,
        )
        if status != _HRESULT_OK:
            raise NativeApiError(
                f"PdhGetFormattedCounterArrayW 读取失败: {_status_text(status)}"
            )

        rows: list[tuple[str, float]] = []
        for index in range(count.value):
            item = items[index]
            if item.FmtValue.CStatus != _HRESULT_OK:
                continue
            name = item.szName
            if not name:
                continue
            rows.append((name, item.FmtValue.doubleValue))
        return rows

    def close(self) -> None:
        """释放 PDH 查询；重复调用安全。"""
        query = self._query
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        if query:
            _pdh.PdhCloseQuery(query)


# --------------------------------------------------------------------------
# kernel32：CPU 时间与内存
# --------------------------------------------------------------------------

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD),
        ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_kernel32.GetSystemTimes.argtypes = [
    ctypes.POINTER(_FileTime),
    ctypes.POINTER(_FileTime),
    ctypes.POINTER(_FileTime),
]
_kernel32.GetSystemTimes.restype = wt.BOOL
_kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
_kernel32.GlobalMemoryStatusEx.restype = wt.BOOL


def system_times() -> tuple[int, int, int]:
    """读取系统累计 CPU 时间 ``(idle, kernel, user)``，单位 100ns。

    ``kernel`` 已包含 ``idle``：计算占用时用
    ``(Δkernel + Δuser - Δidle) / (Δkernel + Δuser)``。

    Returns:
        三元组 (idle, kernel, user)，单调递增的绝对值。

    Raises:
        NativeApiError: 调用失败。
    """
    idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
    ok = _kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        raise NativeApiError(f"GetSystemTimes 失败: {ctypes.get_last_error()}")
    ticks = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # noqa: E731
    return ticks(idle), ticks(kernel), ticks(user)


def memory_bytes() -> tuple[int, int]:
    """读取物理内存 ``(总量, 可用)``，单位字节。

    Raises:
        NativeApiError: 调用失败。
    """
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise NativeApiError(f"GlobalMemoryStatusEx 失败: {ctypes.get_last_error()}")
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def logical_processor_count() -> int:
    """逻辑处理器数量；平台取不到时返回 0。"""
    import os

    return int(os.cpu_count() or 0)


# --------------------------------------------------------------------------
# DXGI：物理适配器目录
# --------------------------------------------------------------------------


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class _DxgiAdapterDesc1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", wt.UINT),
        ("DeviceId", wt.UINT),
        ("SubSysId", wt.UINT),
        ("Revision", wt.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _Luid),
        ("Flags", wt.UINT),
    ]


#: IDXGIFactory1 的 IID：{770AAE78-F26F-4DBA-A829-253C83D1B387}
_IID_IDXGIFACTORY1 = _Guid(
    0x770AAE78,
    0xF26F,
    0x4DBA,
    (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
)

#: DXGI_ADAPTER_FLAG_SOFTWARE：软件适配器（WARP 等），任务管理器不展示
_ADAPTER_FLAG_SOFTWARE = 0x2

# vtable 槽位：IUnknown(0..2) → IDXGIFactory(3..11) → IDXGIFactory1(12..13)
_VT_RELEASE = 2
_VT_FACTORY_ENUM_ADAPTERS1 = 12
# IDXGIObject 的方法占 3..6（SetPrivateData / SetPrivateDataInterface /
# GetPrivateData / GetParent），IDXGIAdapter 追加 EnumOutputs / GetDesc /
# CheckInterfaceSupport 于 7..9，IDXGIAdapter1 的 GetDesc1 位于槽位 10。
_VT_ADAPTER_GET_DESC1 = 10


@dataclass(frozen=True)
class AdapterInfo:
    """一块物理 GPU 的静态描述。

    Attributes:
        name: 适配器型号名。
        luid_key: ``(LUID 高位, LUID 低位)``，用于与 PDH 实例名关联。
        dedicated_video_memory: 专用显存容量（字节）。
        shared_system_memory: 共享系统内存容量（字节）。
    """

    name: str
    luid_key: tuple[int, int]
    dedicated_video_memory: int
    shared_system_memory: int


def list_adapters() -> list[AdapterInfo]:
    """枚举物理 GPU 适配器（排除 ``DXGI_ADAPTER_FLAG_SOFTWARE``）。

    软件适配器（WARP、远程桌面虚拟显卡）也会注册 GPU Engine 计数器，若不过滤，
    状态栏会多出一个恒为 0% 的假 GPU 项。

    Returns:
        物理适配器列表；DXGI 不可用或无适配器时返回空列表。
    """
    try:
        dxgi = ctypes.WinDLL("dxgi")
        create_factory = dxgi.CreateDXGIFactory1
        create_factory.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create_factory.restype = ctypes.c_long
    except (OSError, AttributeError):
        return []

    factory = ctypes.c_void_p()
    if create_factory(ctypes.byref(_IID_IDXGIFACTORY1), ctypes.byref(factory)) != 0:
        return []

    adapters: list[AdapterInfo] = []
    try:
        vtable = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[
            0
        ]
        enum_adapters = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )(vtable[_VT_FACTORY_ENUM_ADAPTERS1])

        for index in range(16):
            adapter = ctypes.c_void_p()
            hr = enum_adapters(factory, index, ctypes.byref(adapter))
            if hr == _DXGI_ERROR_NOT_FOUND:
                break
            if hr != _HRESULT_OK or not adapter:
                break
            try:
                adapter_vtable = ctypes.cast(
                    adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                )[0]
                get_desc = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_DxgiAdapterDesc1)
                )(adapter_vtable[_VT_ADAPTER_GET_DESC1])
                desc = _DxgiAdapterDesc1()
                if get_desc(adapter, ctypes.byref(desc)) != _HRESULT_OK:
                    continue
                if desc.Flags & _ADAPTER_FLAG_SOFTWARE:
                    continue
                adapters.append(
                    AdapterInfo(
                        name=desc.Description,
                        luid_key=(
                            int(desc.AdapterLuid.HighPart),
                            int(desc.AdapterLuid.LowPart),
                        ),
                        dedicated_video_memory=int(desc.DedicatedVideoMemory),
                        shared_system_memory=int(desc.SharedSystemMemory),
                    )
                )
            finally:
                release_adapter = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                    ctypes.cast(
                        adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                    )[0][_VT_RELEASE]
                )
                release_adapter(adapter)
    finally:
        release_factory = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][
                _VT_RELEASE
            ]
        )
        release_factory(factory)
    return adapters
