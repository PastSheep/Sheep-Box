"""项目统一业务异常定义。

所有模块异常均继承自 :class:`SheepBoxError`，便于上层统一捕获与区分。
"""


class SheepBoxError(Exception):
    """项目基础异常，所有自定义业务异常的基类。"""


class ConfigError(SheepBoxError):
    """配置加载或校验失败时抛出（必填缺失、类型/枚举非法、文件不可读）。"""


class OcrError(SheepBoxError):
    """OCR 识别流程失败时抛出。"""


class OcrEngineError(OcrError):
    """OCR 引擎（模型加载 / 推理）失败时抛出。"""


class SystemInfoError(SheepBoxError):
    """系统资源采集失败时抛出（CPU / 内存等必需指标读取失败）。"""


class CaptureError(SheepBoxError):
    """窗口截图失败时抛出，所有截图相关异常的基类。"""


class WindowNotFoundError(CaptureError):
    """句柄无效或窗口已销毁。"""


class WindowNotVisibleError(CaptureError):
    """窗口不可见或已最小化，无法按「可见即可」的约束截取。"""


class WindowOutOfScreenError(CaptureError):
    """窗口客户区与任何屏幕区域都没有交集（被拖到屏幕外或无桌面会话）。"""


class CaptureRegionError(CaptureError):
    """请求区域完全落在客户区之外，或客户区尺寸非法。"""


class CaptureOccludedError(CaptureError):
    """目标区域被其它窗口覆盖，屏幕口径下截到的将是遮挡者的内容。"""


class CaptureUnavailableError(CaptureError):
    """运行环境不满足截图前提（进程 DPI 感知无法建立、独占全屏、无桌面）。"""


class CaptureBackendError(CaptureError):
    """具体抓取后端调用失败，附带 Win32 错误码与失败步骤。"""
