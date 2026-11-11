"""DXGI 桌面复制的 ctypes 绑定。

只封装 ``IDXGIOutputDuplication`` 一条路径，不含业务判断：建会话、拉一帧、裁剪
指定区域、读回 BGRA，失效时抛 :class:`AccessLostError` 由上层决定是否重建。

槽位依据 ``d3d11.h`` / ``dxgi1_2.h`` 的接口声明顺序（IUnknown 占 0~2）：

- ``IDXGIFactory1.EnumAdapters1`` = 12；
- ``IDXGIAdapter.EnumOutputs`` = 7，``IDXGIOutput.GetDesc`` = 7；
- ``IDXGIOutput1.DuplicateOutput`` = 22（19~21 依次是三个 1 版方法）；
- ``IDXGIOutputDuplication``：GetDesc 7、AcquireNextFrame 8、ReleaseFrame 14；
- ``ID3D11Device.CreateTexture2D`` = 5；
- ``ID3D11DeviceContext``：Map 14、Unmap 15、CopyResource 47。

坐标系提醒：复制出来的图只覆盖单个输出，坐标是**输出本地**的；调用方要先减去
``output_rect`` 的左上角再传进来。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes as wt
from dataclasses import dataclass
from typing import Any

from common.exceptions import CaptureBackendError, CaptureUnavailableError

if sys.platform != "win32":  # pragma: no cover - 仅 Windows 可用
    raise ImportError("service.capture.backends._dxgi_native 仅支持 Windows")

logger = logging.getLogger(__name__)

__all__ = [
    "AccessLostError",
    "DuplicationSession",
    "HresultError",
    "virtual_contains",
]

# --------------------------------------------------------------------------
# 基础结构与 COM 辅助
# ---------------------------------------------------------------------------


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(
    data1: int,
    data2: int,
    data3: int,
    tail: tuple[int, int, int, int, int, int, int, int],
) -> _Guid:
    """按 IID 的 8 段字节构造 GUID。

    Args:
        data1: 第一段 32 位。
        data2: 第二段 16 位。
        data3: 第三段 16 位。
        tail: 末 8 字节。

    Returns:
        GUID 结构。
    """
    return _Guid(data1, data2, data3, (ctypes.c_ubyte * 8)(*tail))


_IID_IDXGIFACTORY1 = _guid(
    0x770AAE78, 0xF26F, 0x4DBA, (0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
)
_IID_IDXGIOUTPUT1 = _guid(
    0x00CDDEA8, 0x939B, 0x4B83, (0xA3, 0x40, 0xA6, 0x85, 0x22, 0x66, 0x66, 0xCC)
)
_IID_ID3D11TEXTURE2D = _guid(
    0x6F15AAF2, 0xD208, 0x4E89, (0x9A, 0xB4, 0x48, 0x95, 0x35, 0xD3, 0x4F, 0x9C)
)


class _Rational(ctypes.Structure):
    _fields_ = [("Numerator", wt.UINT), ("Denominator", wt.UINT)]


class _ModeDesc(ctypes.Structure):
    _fields_ = [
        ("Width", wt.UINT),
        ("Height", wt.UINT),
        ("RefreshRate", _Rational),
        ("Format", wt.UINT),
        ("ScanlineOrdering", wt.UINT),
        ("Scaling", wt.UINT),
    ]


class _OutduplDesc(ctypes.Structure):
    _fields_ = [
        ("ModeDesc", _ModeDesc),
        ("Rotation", wt.UINT),
        ("DesktopImageInSystemMemory", wt.BOOL),
    ]


class _OutputDesc(ctypes.Structure):
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("DesktopCoordinates", wt.RECT),
        ("AttachedToDesktop", wt.BOOL),
        ("Rotation", wt.UINT),
        ("Monitor", ctypes.c_void_p),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class _PointerPosition(ctypes.Structure):
    _fields_ = [("Position", _Point), ("Visible", wt.BOOL)]


class _FrameInfo(ctypes.Structure):
    _fields_ = [
        ("LastPresentTime", ctypes.c_longlong),
        ("LastMouseUpdateTime", ctypes.c_longlong),
        ("AccumulatedFrames", wt.UINT),
        ("RectsCoalesced", wt.BOOL),
        ("ProtectedContentMaskedOut", wt.BOOL),
        ("PointerPosition", _PointerPosition),
        ("TotalMetadataBufferSize", wt.UINT),
        ("PointerShapeBufferSize", wt.UINT),
    ]


class _SampleDesc(ctypes.Structure):
    _fields_ = [("Count", wt.UINT), ("Quality", wt.UINT)]


class _Texture2DDesc(ctypes.Structure):
    _fields_ = [
        ("Width", wt.UINT),
        ("Height", wt.UINT),
        ("MipLevels", wt.UINT),
        ("ArraySize", wt.UINT),
        ("Format", wt.UINT),
        ("SampleDesc", _SampleDesc),
        ("Usage", wt.UINT),
        ("BindFlags", wt.UINT),
        ("CPUAccessFlags", wt.UINT),
        ("MiscFlags", wt.UINT),
    ]


class _MappedSubresource(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", wt.UINT),
        ("DepthPitch", wt.UINT),
    ]


# --------------------------------------------------------------------------
# HRESULT 常量
# --------------------------------------------------------------------------


def _signed(hr: int) -> int:
    """把 32 位 HRESULT 转成 ctypes.c_long 的符号值，便于比较。"""
    return ctypes.c_long(hr).value


_HRESULT_OK = 0
_DXGI_ERROR_NOT_FOUND = _signed(0x887A0002)
_DXGI_ERROR_ACCESS_LOST = _signed(0x887A0026)
_DXGI_ERROR_WAIT_TIMEOUT = _signed(0x887A0027)
_DXGI_ERROR_UNSUPPORTED = _signed(0x887A0004)
_DXGI_ERROR_NOT_CURRENTLY_AVAILABLE = _signed(0x887A0022)
_DXGI_ERROR_SESSION_DISCONNECTED = _signed(0x887A0028)
_DXGI_ERROR_DEVICE_REMOVED = _signed(0x887A0005)
_DXGI_ERROR_DEVICE_RESET = _signed(0x887A0007)

# 只保留常见的失败原因，未知码统一按 16 进制展示
_ERROR_TEXT: dict[int, str] = {
    _DXGI_ERROR_ACCESS_LOST: "桌面复制失效（分辨率/全屏切换或锁屏）",
    _DXGI_ERROR_UNSUPPORTED: "当前桌面模式不支持桌面复制（如 8bpp 或非 DWM 桌面）",
    _DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: "并发复制已达上限（同一会话最多 4 个）",
    _DXGI_ERROR_SESSION_DISCONNECTED: "当前会话已断开",
    _DXGI_ERROR_DEVICE_REMOVED: "显卡设备已移除",
    _DXGI_ERROR_DEVICE_RESET: "显卡设备已重置",
}

# --------------------------------------------------------------------------
# 接口方法槽位
# --------------------------------------------------------------------------

_VT_QI = 0
_VT_RELEASE = 2
_VT_FACTORY_ENUM_ADAPTERS1 = 12
_VT_ADAPTER_ENUM_OUTPUTS = 7
_VT_OUTPUT_GET_DESC = 7
_VT_OUTPUT1_DUPLICATE_OUTPUT = 22
_VT_DUPL_GET_DESC = 7
_VT_DUPL_ACQUIRE = 8
_VT_DUPL_RELEASE_FRAME = 14
_VT_DEVICE_CREATE_TEXTURE2D = 5
_VT_CONTEXT_MAP = 14
_VT_CONTEXT_UNMAP = 15
_VT_CONTEXT_COPY_RESOURCE = 47

# 常量
_DRIVER_TYPE_UNKNOWN = 0
_D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
_D3D11_SDK_VERSION = 7
_DXGI_FORMAT_B8G8R8A8_UNORM = 87
_D3D11_USAGE_STAGING = 3
_D3D11_CPU_ACCESS_READ = 0x20000
_D3D11_MAP_READ = 1
_DXGI_MODE_ROTATION_IDENTITY = 1
_MAX_ADAPTERS = 16
_MAX_OUTPUTS = 8


class HresultError(CaptureBackendError):
    """一个 HRESULT 调用返回了失败码。"""


class AccessLostError(CaptureBackendError):
    """桌面复制失效，会话需要重建。"""


def _describe(hr: int, what: str) -> str:
    """把 HRESULT 转成可读的失败说明。

    Args:
        hr: 返回码。
        what: 出错的操作名。

    Returns:
        一句中文说明。
    """
    reason = _ERROR_TEXT.get(hr)
    code = f"0x{hr & 0xFFFFFFFF:08X}"
    return f"{what} 失败（{code}）{': ' + reason if reason else ''}"


def _vtable(obj: ctypes.c_void_p) -> Any:
    """取对象的 vtable 指针数组。"""
    return ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]


def _method(obj: ctypes.c_void_p, slot: int, *argtypes: Any) -> Any:
    """按槽位取一个 COM 方法。

    Args:
        obj: 接口指针。
        slot: vtable 槽位。
        argtypes: 除 ``this`` 外的参数类型。

    Returns:
        可调用的函数指针；返回类型统一按 HRESULT（c_long）解释。
    """
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return prototype(_vtable(obj)[slot])


def _release(obj: ctypes.c_void_p | None) -> None:
    """释放一个 COM 接口，空指针安全。"""
    if not obj:
        return
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
        _vtable(obj)[_VT_RELEASE]
    )
    release(obj)


def _query_interface(obj: ctypes.c_void_p, iid: _Guid) -> ctypes.c_void_p:
    """QueryInterface 到指定 IID。

    Args:
        obj: 源接口。
        iid: 目标 IID。

    Returns:
        新接口指针；不支持时为空指针。
    """
    query = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(ctypes.c_void_p),
    )(_vtable(obj)[_VT_QI])
    result = ctypes.c_void_p()
    hr = query(obj, ctypes.byref(iid), ctypes.byref(result))
    if hr != _HRESULT_OK:
        return ctypes.c_void_p()
    return result


@dataclass(frozen=True)
class _Output:
    """一个显示器输出的几何信息。"""

    output: ctypes.c_void_p
    left: int
    top: int
    width: int
    height: int


def virtual_contains(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    """判断一个屏幕矩形是否包含某点。

    Args:
        rect: ``(left, top, width, height)``。
        point: 屏幕坐标。

    Returns:
        包含为真。
    """
    left, top, width, height = rect
    return left <= point[0] < left + width and top <= point[1] < top + height


class DuplicationSession:
    """单输出桌面复制会话。

    一个输出上只能有一个复制接口，因此一个会话只覆盖一个显示器；跨屏需求由上层
    按区域所在输出切换或直接报不支持。
    """

    def __init__(self) -> None:
        self._device: ctypes.c_void_p | None = None
        self._context: ctypes.c_void_p | None = None
        self._output: ctypes.c_void_p | None = None
        self._duplication: ctypes.c_void_p | None = None
        self._staging: ctypes.c_void_p | None = None
        self._staging_size: tuple[int, int] = (0, 0)
        self._frame_pending = False
        self._output_rect = (0, 0, 0, 0)
        self._image_size = (0, 0)
        self._last: tuple[tuple[int, int, int, int], bytes] | None = None

    # ---------------------------------------------------------------- 属性

    @property
    def output_rect(self) -> tuple[int, int, int, int]:
        """当前输出在虚拟桌面上的矩形 ``(left, top, width, height)``。"""
        return self._output_rect

    @property
    def image_size(self) -> tuple[int, int]:
        """复制图像的像素尺寸（未裁剪的整输出）。"""
        return self._image_size

    @property
    def opened(self) -> bool:
        """会话是否已建立。"""
        return self._duplication is not None

    # ---------------------------------------------------------------- 打开

    def open(self, point: tuple[int, int]) -> None:
        """建立会话，选择包含 ``point`` 的输出。

        Args:
            point: 屏幕物理坐标。

        Raises:
            CaptureUnavailableError: DXGI 不可用、无输出或复制接口创建失败。
        """
        if self._duplication is not None:
            return
        try:
            dxgi = ctypes.WinDLL("dxgi")
        except OSError as exc:  # pragma: no cover - Windows 必有 dxgi.dll
            raise CaptureUnavailableError(f"无法加载 dxgi.dll：{exc}") from exc

        create_factory = dxgi.CreateDXGIFactory1
        create_factory.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create_factory.restype = ctypes.c_long
        factory = ctypes.c_void_p()
        if create_factory(ctypes.byref(_IID_IDXGIFACTORY1), ctypes.byref(factory)) != 0:
            raise CaptureUnavailableError("CreateDXGIFactory1 失败，无法使用桌面复制")
        if not factory:
            raise CaptureUnavailableError("CreateDXGIFactory1 返回空工厂")

        try:
            self._build(factory, point)
        finally:
            _release(factory)
        if self._duplication is None:
            raise CaptureUnavailableError(f"没有显示器覆盖坐标 {point}，无法复制桌面")
        self._warm_up()

    def _warm_up(self) -> None:
        """丢弃复制接口建立后的第一帧。

        ``DuplicateOutput`` 之后第一次 ``AcquireNextFrame`` 常常返回共享纹理刚分配
        时的空帧（整张全黑），若不丢弃，业务首次抓取会拿到一张无内容的图。这里只
        拉一次、读一个像素，然后立刻释放；失败不阻断打开，后续抓取会给出真实错误。
        """
        try:
            self._grab_frame((0, 0, 1, 1), 200)
        except CaptureBackendError as exc:
            logger.debug("桌面复制预热失败（忽略）：%s", exc)

    def _build(self, factory: ctypes.c_void_p, point: tuple[int, int]) -> None:
        """遍历适配器与输出，找到覆盖目标点的那个并建复制接口。"""
        enum_adapters = _method(
            factory,
            _VT_FACTORY_ENUM_ADAPTERS1,
            wt.UINT,
            ctypes.POINTER(ctypes.c_void_p),
        )
        for index in range(_MAX_ADAPTERS):
            adapter = ctypes.c_void_p()
            hr = enum_adapters(factory, index, ctypes.byref(adapter))
            if hr == _DXGI_ERROR_NOT_FOUND:
                break
            if hr != _HRESULT_OK:
                raise HresultError(_describe(hr, "EnumAdapters1"))
            if not adapter:
                continue
            try:
                if self._try_adapter(adapter, point):
                    return
            finally:
                # device 会自行持有 adapter 引用，这里可以立刻放掉
                _release(adapter)

    def _try_adapter(self, adapter: ctypes.c_void_p, point: tuple[int, int]) -> bool:
        """在一个适配器上尝试建设备与复制接口。"""
        device = ctypes.c_void_p()
        context = ctypes.c_void_p()
        level = wt.UINT()
        try:
            d3d11 = ctypes.WinDLL("d3d11")
        except OSError as exc:  # pragma: no cover - Windows 必有 d3d11.dll
            raise CaptureUnavailableError(f"无法加载 d3d11.dll：{exc}") from exc

        create = d3d11.D3D11CreateDevice
        create.argtypes = [
            ctypes.c_void_p,
            wt.INT,
            ctypes.c_void_p,
            wt.UINT,
            ctypes.c_void_p,
            wt.UINT,
            wt.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wt.UINT),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        create.restype = ctypes.c_long
        hr = create(
            adapter,
            _DRIVER_TYPE_UNKNOWN,
            None,
            _D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            None,
            0,
            _D3D11_SDK_VERSION,
            ctypes.byref(device),
            ctypes.byref(level),
            ctypes.byref(context),
        )
        if hr != _HRESULT_OK or not device or not context:
            _release(device)
            _release(context)
            return False

        try:
            output = self._find_output(adapter, point)
        except (CaptureUnavailableError, HresultError):
            # ``_find_output`` 在旋转屏、EnumOutputs 失败时抛错，此时 device/
            # context 还没交给下面的 try/finally，不放就随栈帧泄漏；显式 backend
            # 或 auto 判黑走 dxgi 时每次抓取都会重走一次。
            _release(device)
            _release(context)
            raise
        if output is None:
            _release(device)
            _release(context)
            return False

        output1 = ctypes.c_void_p()
        duplication = ctypes.c_void_p()
        owned = False
        try:
            output1 = _query_interface(output.output, _IID_IDXGIOUTPUT1)
            if not output1:
                raise CaptureUnavailableError(
                    "IDXGIOutput 不支持桌面复制（需要 Windows 8+）"
                )
            duplicate = _method(
                output1,
                _VT_OUTPUT1_DUPLICATE_OUTPUT,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr = duplicate(output1, device, ctypes.byref(duplication))
            if hr != _HRESULT_OK or not duplication:
                raise CaptureUnavailableError(_describe(hr, "DuplicateOutput"))
            owned = True
        finally:
            _release(output.output)
            if not owned:
                # 失败路径必须放掉已经创建的 COM 对象：它们只是局部指针，
                # 随栈帧丢弃会泄漏 D3D 设备与适配器引用，auto 链每次重试
                # 都会再漏一份。
                _release(output1)
                _release(device)
                _release(context)

        self._device = device
        self._context = context
        self._output = output1
        self._duplication = duplication
        self._output_rect = (output.left, output.top, output.width, output.height)
        self._image_size = self._read_image_size()
        return True

    def _find_output(
        self, adapter: ctypes.c_void_p, point: tuple[int, int]
    ) -> _Output | None:
        """在适配器上找覆盖目标点的输出。"""
        enum_outputs = _method(
            adapter, _VT_ADAPTER_ENUM_OUTPUTS, wt.UINT, ctypes.POINTER(ctypes.c_void_p)
        )
        for index in range(_MAX_OUTPUTS):
            output = ctypes.c_void_p()
            hr = enum_outputs(adapter, index, ctypes.byref(output))
            if hr == _DXGI_ERROR_NOT_FOUND:
                break
            if hr != _HRESULT_OK:
                raise HresultError(_describe(hr, "EnumOutputs"))
            if not output:
                continue
            desc = _OutputDesc()
            get_desc = _method(output, _VT_OUTPUT_GET_DESC, ctypes.POINTER(_OutputDesc))
            if get_desc(output, ctypes.byref(desc)) != _HRESULT_OK:
                _release(output)
                continue
            if desc.Rotation != _DXGI_MODE_ROTATION_IDENTITY:
                _release(output)
                raise CaptureUnavailableError(
                    "显示器处于旋转状态，桌面复制坐标与屏幕坐标不一致，暂不支持"
                )
            if not desc.AttachedToDesktop:
                _release(output)
                continue
            rect = desc.DesktopCoordinates
            left, top = int(rect.left), int(rect.top)
            width, height = int(rect.right) - left, int(rect.bottom) - top
            if virtual_contains((left, top, width, height), point):
                return _Output(output, left, top, width, height)
            _release(output)
        return None

    def _read_image_size(self) -> tuple[int, int]:
        """读复制接口的模式尺寸，用作 staging 与越界校验的基准。"""
        assert self._duplication is not None
        desc = _OutduplDesc()
        get_desc = _method(
            self._duplication, _VT_DUPL_GET_DESC, ctypes.POINTER(_OutduplDesc)
        )
        if get_desc(self._duplication, ctypes.byref(desc)) != _HRESULT_OK:
            return self._output_rect[2], self._output_rect[3]
        width = int(desc.ModeDesc.Width) or self._output_rect[2]
        height = int(desc.ModeDesc.Height) or self._output_rect[3]
        return width, height

    # ---------------------------------------------------------------- 抓帧

    def grab(self, region: tuple[int, int, int, int], timeout_ms: int = 0) -> bytes:
        """抓取桌面一帧并裁出区域。

        Args:
            region: 输出本地坐标 ``(x, y, width, height)``。
            timeout_ms: 等待新帧的毫秒数。

        Returns:
            BGRA 像素，脏行已被压紧。

        Raises:
            AccessLostError: 复制失效，需要重建会话。
            CaptureBackendError: 无新帧且无可用缓存，或读取失败。
            CaptureUnavailableError: 区域超出当前输出。
        """
        self._validate_region(region)
        data = self._grab_frame(region, timeout_ms)
        if data is None:
            if self._last is not None and self._last[0] == region:
                return self._last[1]
            data = self._grab_frame(region, 100)
            if data is None:
                raise CaptureBackendError(
                    "桌面复制在一段时间内没有产生新帧，且无可用缓存"
                )
        self._last = (region, data)
        return data

    def _validate_region(self, region: tuple[int, int, int, int]) -> None:
        """区域必须完全落在当前输出内，跨输出不在这里拼接。"""
        x, y, width, height = region
        image_width, image_height = self._image_size
        if width <= 0 or height <= 0:
            raise CaptureBackendError(f"裁剪区域尺寸非法：{width}x{height}")
        if x < 0 or y < 0 or x + width > image_width or y + height > image_height:
            raise CaptureUnavailableError(
                f"区域 {region} 超出当前输出 {image_width}x{image_height}，"
                "跨显示器截图不在该后端支持范围内"
            )

    def _grab_frame(
        self, region: tuple[int, int, int, int], timeout_ms: int
    ) -> bytes | None:
        """拉一帧；超时返回 ``None``。"""
        if self._duplication is None:
            raise CaptureBackendError("桌面复制会话尚未打开")
        if self._frame_pending:
            self._release_frame()

        info = _FrameInfo()
        resource = ctypes.c_void_p()
        acquire = _method(
            self._duplication,
            _VT_DUPL_ACQUIRE,
            wt.UINT,
            ctypes.POINTER(_FrameInfo),
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = acquire(
            self._duplication, timeout_ms, ctypes.byref(info), ctypes.byref(resource)
        )
        if hr == _DXGI_ERROR_WAIT_TIMEOUT:
            return None
        if hr == _DXGI_ERROR_ACCESS_LOST:
            raise AccessLostError("桌面复制失效，需要重建")
        if hr != _HRESULT_OK or not resource:
            raise HresultError(_describe(hr, "AcquireNextFrame"))

        self._frame_pending = True
        try:
            texture = _query_interface(resource, _IID_ID3D11TEXTURE2D)
            if not texture:
                raise CaptureBackendError("桌面包不是 ID3D11Texture2D")
            try:
                return self._read_region(region, texture)
            finally:
                _release(texture)
        finally:
            _release(resource)
            self._release_frame()

    def _read_region(
        self, region: tuple[int, int, int, int], texture: ctypes.c_void_p
    ) -> bytes:
        """把指定区域从 GPU 纹理拷到 staging 再读回内存。"""
        staging = self._ensure_staging()
        assert self._context is not None
        copy = _method(
            self._context,
            _VT_CONTEXT_COPY_RESOURCE,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        copy(self._context, staging, texture)

        mapped = _MappedSubresource()
        map_fn = _method(
            self._context,
            _VT_CONTEXT_MAP,
            ctypes.c_void_p,
            wt.UINT,
            wt.UINT,
            wt.UINT,
            ctypes.POINTER(_MappedSubresource),
        )
        hr = map_fn(
            self._context,
            staging,
            0,
            _D3D11_MAP_READ,
            0,
            ctypes.byref(mapped),
        )
        if hr != _HRESULT_OK:
            raise HresultError(_describe(hr, "Map"))
        try:
            return self._read_rows(mapped, region)
        finally:
            unmap = _method(self._context, _VT_CONTEXT_UNMAP, ctypes.c_void_p, wt.UINT)
            unmap(self._context, staging, 0)

    def _read_rows(
        self, mapped: _MappedSubresource, region: tuple[int, int, int, int]
    ) -> bytes:
        """按行把映射内存里的目标区域拷出来。"""
        x, y, width, height = region
        row_bytes = width * 4
        pitch = int(mapped.RowPitch)
        base = int(mapped.pData or 0)
        if base == 0:
            raise CaptureBackendError("Map 返回了空指针")
        output = bytearray(row_bytes * height)
        for row in range(height):
            source = base + (y + row) * pitch + x * 4
            output[row * row_bytes : (row + 1) * row_bytes] = ctypes.string_at(
                source, row_bytes
            )
        return bytes(output)

    def _ensure_staging(self) -> ctypes.c_void_p:
        """创建（或复用）与图像同尺寸的 staging 纹理。"""
        width, height = self._image_size
        if self._staging is not None and self._staging_size == (width, height):
            assert self._staging is not None
            return self._staging
        self._release_staging()
        if self._device is None:
            raise CaptureBackendError("D3D11 设备尚未创建")
        desc = _Texture2DDesc(
            Width=width,
            Height=height,
            MipLevels=1,
            ArraySize=1,
            Format=_DXGI_FORMAT_B8G8R8A8_UNORM,
            SampleDesc=_SampleDesc(1, 0),
            Usage=_D3D11_USAGE_STAGING,
            BindFlags=0,
            CPUAccessFlags=_D3D11_CPU_ACCESS_READ,
            MiscFlags=0,
        )
        texture = ctypes.c_void_p()
        create = _method(
            self._device,
            _VT_DEVICE_CREATE_TEXTURE2D,
            ctypes.POINTER(_Texture2DDesc),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = create(self._device, ctypes.byref(desc), None, ctypes.byref(texture))
        if hr != _HRESULT_OK or not texture:
            raise HresultError(_describe(hr, "CreateTexture2D"))
        self._staging = texture
        self._staging_size = (width, height)
        return texture

    def _release_frame(self) -> None:
        """释放当前帧的占用；重复调用安全。"""
        if self._duplication is None or not self._frame_pending:
            return
        release = _method(self._duplication, _VT_DUPL_RELEASE_FRAME)
        release(self._duplication)
        self._frame_pending = False

    def _release_staging(self) -> None:
        """释放 staging 纹理。"""
        _release(self._staging)
        self._staging = None
        self._staging_size = (0, 0)

    # ---------------------------------------------------------------- 关闭

    def close(self) -> None:
        """释放全部 COM 资源；重复调用安全。"""
        if self._duplication is not None and self._frame_pending:
            self._release_frame()
        _release(self._duplication)
        _release(self._output)
        self._release_staging()
        _release(self._context)
        _release(self._device)
        self._duplication = None
        self._output = None
        self._context = None
        self._device = None
        self._frame_pending = False
        self._last = None
