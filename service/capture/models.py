"""窗口区域截图的数据模型。

只描述「看到了什么、怎么描述的」：不含 OCR、阈值、定时或编码策略。区域有两种
描述方式——像素（``CaptureRegion``）与比例（``NormalizedRegion``）；比例形态用于
「窗口宽高比固定、分辨率可变」的场景（典型是游戏窗口）。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "BackendCapabilities",
    "CaptureOptions",
    "CaptureRegion",
    "NormalizedRegion",
    "ScreenFrame",
    "WindowInfo",
]

SPACE_CLIENT = "client"
SPACE_SCREEN = "screen"


def _clamp01(value: float) -> float:
    """把比例值裁剪到 ``[0, 1]``。

    Args:
        value: 任意浮点比例。

    Returns:
        裁剪后的比例。
    """
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class CaptureRegion:
    """相对窗口客户区左上角的矩形，单位一律是物理像素。

    Attributes:
        x: 左偏移（相对客户区）。
        y: 上偏移（相对客户区）。
        width: 宽，必须为正。
        height: 高，必须为正。
    """

    x: int
    y: int
    width: int
    height: int

    def clamp(self, client_width: int, client_height: int) -> CaptureRegion:
        """把区域裁剪到 ``[0, client_width] × [0, client_height]`` 内。

        完全越界时返回零尺寸区域（:attr:`empty` 为真），是否报错由调用方决定。

        Args:
            client_width: 客户区宽。
            client_height: 客户区高。

        Returns:
            裁剪后的新区域，不自修改。
        """
        x0 = max(self.x, 0)
        y0 = max(self.y, 0)
        x1 = min(self.x + self.width, client_width)
        y1 = min(self.y + self.height, client_height)
        return CaptureRegion(x0, y0, max(x1 - x0, 0), max(y1 - y0, 0))

    @classmethod
    def full(cls, client_width: int, client_height: int) -> CaptureRegion:
        """构造覆盖整个客户区的区域。

        Args:
            client_width: 客户区宽。
            client_height: 客户区高。

        Returns:
            从 ``(0, 0)`` 起、尺寸为客户区的区域。
        """
        return cls(0, 0, max(client_width, 0), max(client_height, 0))

    @property
    def empty(self) -> bool:
        """区域是否为空（宽或高非正）。"""
        return self.width <= 0 or self.height <= 0


@dataclass(frozen=True)
class NormalizedRegion:
    """按比例描述的区域，各分量取值 0~1。

    窗口宽高比固定、分辨率可变时用它：任务区域只存比例，运行时按当前尺寸换算，
    从 1280×720 切到 1920×1080 不需要改任何配置。

    Attributes:
        nx: 左边界比例。
        ny: 上边界比例。
        nw: 宽比例。
        nh: 高比例。
    """

    nx: float
    ny: float
    nw: float
    nh: float

    def to_pixels(self, width: int, height: int) -> CaptureRegion:
        """按目标尺寸换算成像素区域。

        比例会先裁剪到 0~1；换算后保证宽高至少 1 像素、且不超出目标尺寸。

        Args:
            width: 目标宽（客户区或屏幕占位，取决于调用方口径）。
            height: 目标高。

        Returns:
            像素区域。

        Raises:
            ValueError: 目标尺寸非正。
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"目标尺寸必须为正，收到 {width}x{height}")

        nx = _clamp01(self.nx)
        ny = _clamp01(self.ny)
        nw = _clamp01(self.nw)
        nh = _clamp01(self.nh)

        x = min(round(nx * width), width - 1)
        y = min(round(ny * height), height - 1)
        w = max(1, round(nw * width))
        h = max(1, round(nh * height))
        w = min(w, width - x)
        h = min(h, height - y)
        return CaptureRegion(x, y, w, h)


@dataclass(frozen=True)
class WindowInfo:
    """一个顶层窗口的可截取性描述。

    Attributes:
        hwnd: 窗口句柄。
        title: 窗口标题。
        class_name: 窗口类名。
        process_id: 进程 ID。
        process_name: 进程名（``QueryFullProcessImageNameW`` 取不到时为空串）。
        client_width: 客户区尺寸（窗口表面口径）。
        client_height: 客户区尺寸（窗口表面口径）。
        screen_width: 客户区在屏幕上的实际占位（物理像素）。DPI-unaware 的窗口
            会被系统位图拉伸，因此该值可能大于 ``client_width``。
        screen_height: 同上。
        dpi: ``GetDpiForWindow`` 的结果；取不到时为 96。
        visible: 是否可见。
        minimized: 是否最小化。
        frame_rect: 窗框在屏幕上的矩形 ``(left, top, width, height)``，
            优先 DWM 扩展框，排除阴影与圆角留白。
        client_origin: 客户区左上角的屏幕坐标 ``(x, y)``。
    """

    hwnd: int
    title: str
    class_name: str
    process_id: int
    process_name: str
    client_width: int
    client_height: int
    screen_width: int
    screen_height: int
    dpi: int
    visible: bool
    minimized: bool
    frame_rect: tuple[int, int, int, int]
    client_origin: tuple[int, int]

    @property
    def capturable(self) -> bool:
        """当前状态下是否具备截取条件（可见且未最小化）。"""
        return self.visible and not self.minimized

    @property
    def aspect_ratio(self) -> float:
        """客户区宽高比；尺寸非正时返回 0。"""
        if self.screen_width <= 0 or self.screen_height <= 0:
            return 0.0
        return self.screen_width / self.screen_height


@dataclass(frozen=True)
class CaptureOptions:
    """一次抓取的策略开关。

    Attributes:
        backend: ``auto`` / ``screen`` / ``window`` / ``dxgi`` / ``wgc``。
            ``auto`` 先试窗口表面，判黑后退屏幕；``screen`` 直接抓屏幕。
        space: 区域口径，``client``（窗口表面像素）或 ``screen``（屏幕物理像素）。
            为 ``screen`` 时区域按 ``screen_width / client_width`` 缩放。
        prefer_screen: ``auto`` 模式下直接走屏幕帧。
        detect_blank: 窗口表面判黑后是否自动退屏幕。
        verify_occlusion: 是否在抓取前校验目标区域是否被其它窗口覆盖。
        strict_foreground: 遮挡校验升级为「目标窗口必须是前台窗口」。
        clamp_region: 越界时是否钳制（``False`` 则直接抛 ``CaptureRegionError``）。
        include_frame: 预留：是否截含标题栏的非客户区，首版未实现。
    """

    backend: str = "auto"
    space: str = SPACE_CLIENT
    prefer_screen: bool = False
    detect_blank: bool = True
    verify_occlusion: bool = True
    strict_foreground: bool = False
    clamp_region: bool = True
    include_frame: bool = False

    def __post_init__(self) -> None:
        """校验枚举取值。

        Raises:
            ValueError: ``backend`` 或 ``space`` 不在允许集合内。
        """
        if self.backend not in {"auto", "screen", "window", "dxgi", "wgc"}:
            raise ValueError(f"未知 backend: {self.backend!r}")
        if self.space not in {SPACE_CLIENT, SPACE_SCREEN}:
            raise ValueError(f"未知 space: {self.space!r}")


@dataclass(frozen=True)
class ScreenFrame:
    """一次截取的结果。

    像素统一为 BGRA、自上而下（top-down），``stride == width * 4``，不带 alpha
    语义，可直接喂 ``QImage.Format_ARGB32`` 或 numpy ``reshape(height, width, 4)``。

    Attributes:
        width: 像素宽。
        height: 像素高。
        data: 像素字节，长度必须为 ``width * height * 4``。
        region: 实际截取的区域（钳制后的值）。
        space: 本帧像素对应的坐标口径。
        backend: 产出本帧的后端标识。
        window: 抓取时的窗口信息。
        timestamp: 抓取时刻的 Unix 时间戳。
        degraded: 是否由回退/降级产生（如窗口表面判黑后改用屏幕）。
        occluded: 区域可能被其它窗口覆盖，内容不一定属于目标窗口。
    """

    width: int
    height: int
    data: bytes
    region: CaptureRegion
    space: str
    backend: str
    window: WindowInfo
    timestamp: float
    degraded: bool = False
    occluded: bool = False

    def __post_init__(self) -> None:
        """校验尺寸与缓冲长度一致。

        Raises:
            ValueError: 尺寸非正或缓冲长度不匹配。
        """
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"非法帧尺寸: {self.width}x{self.height}")
        if len(self.data) != self.width * self.height * 4:
            raise ValueError(
                f"缓冲长度 {len(self.data)} 与 {self.width}x{self.height}*4 不一致"
            )

    @property
    def stride(self) -> int:
        """每行字节数（恒等于 ``width * 4``）。"""
        return self.width * 4


@dataclass(frozen=True)
class BackendCapabilities:
    """抓取后端的能力声明，用于自动择优与业务侧判断。

    Attributes:
        name: 后端标识（与 ``ScreenFrame.backend`` 一致）。
        continuous: 是否支持连续拉帧（无需每次重复初始化）。
        occluded_ok: 窗口被遮挡时是否仍能拿到目标窗口自身的内容。
        exclusive_fullscreen_ok: 独占全屏下是否可用。
        needs_external_dep: 是否依赖第三方包。
        notes: 一句话补充说明。
    """

    name: str
    continuous: bool = False
    occluded_ok: bool = False
    exclusive_fullscreen_ok: bool = False
    needs_external_dep: bool = False
    notes: str = ""


def blank_ratio(data: bytes, *, threshold: int = 8) -> float:
    """估算「无内容」程度，用于判断窗口表面是否为黑图或单色图。

    按固定步长采样（约 2000 个点），避免对 4K 帧做全量扫描。

    Args:
        data: BGRA 像素字节。
        threshold: 亮度阈值，RGB 三分量都低于该值视为黑像素。

    Returns:
        黑像素或「与首个采样点同色」的占比（0~1），两者取大者。
    """
    count = len(data) // 4
    if count == 0:
        return 1.0
    stride = max(1, count // 2000) * 4
    limit = len(data) - 3
    first_dark = all(channel < threshold for channel in data[0:3])
    first = data[0:3]
    dark = 0
    same = 0
    total = 0
    for offset in range(0, limit, stride):
        r, g, b = data[offset], data[offset + 1], data[offset + 2]
        total += 1
        if r < threshold and g < threshold and b < threshold:
            dark += 1
        # 只有「首像素就是暗色」时，单色才算无内容；否则纯白窗口会被误判
        if first_dark and (r, g, b) == (first[0], first[1], first[2]):
            same += 1
    if total == 0:
        return 1.0
    return float(max(dark, same)) / float(total)
