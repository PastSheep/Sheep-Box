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
