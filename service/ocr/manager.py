"""OCR 管理器：模块对外统一入口。

职责：
- 按配置的模型模式（``tiny/small/medium/all``）加载引擎；
- **资源控制**：非 ``all`` 模式只同时加载一个规格实例，切换时释放旧实例；
- **规格热切换**：``set_model_spec`` 运行时切换，无需重启；
- **配置热更新**：识别前检测配置变化（模式 / 默认规格 / 设备），变化后自动
  重建引擎；重建为**原子替换**，失败保留旧引擎，配置修复后下次识别自动重试。

对外接口：``recognize(image: bytes | str) -> OCRResult``（字节流 / base64 输入、
结构化输出）。
"""

import base64
import logging
from pathlib import Path
from types import TracebackType

from common.exceptions import OcrEngineError, OcrError
from config.manager import ConfigManager
from config.schema import (
    ModelMode,
    ModelSpec,
    ModelSpecPaths,
    OcrConfig,
    OcrThresholdConfig,
)
from service.ocr.device import DevicePlan, resolve_device
from service.ocr.engine import OCREngine
from service.ocr.models import OCRResult

logger = logging.getLogger(__name__)

_REQUIRED_SPECS = (ModelSpec.TINY, ModelSpec.SMALL, ModelSpec.MEDIUM)
_DATA_URI_PREFIX = "data:"


def _coerce_spec(spec: ModelSpec | str) -> ModelSpec:
    """把 ``ModelSpec`` 或字符串转换为合法规格。

    Args:
        spec: 模型规格枚举或字符串（``tiny/small/medium``）。

    Returns:
        合法规格枚举。

    Raises:
        OcrError: 非法规格（含把 ``all`` 当规格传入）。
    """
    if isinstance(spec, ModelSpec):
        return spec
    try:
        return ModelSpec(spec)
    except ValueError as exc:
        raise OcrError(f"非法的模型规格: {spec}") from exc


def _decode_base64(payload: str) -> bytes:
    """把 base64 文本（可含 ``data:...;base64,`` 前缀与空白）解码为字节。

    Args:
        payload: base64 文本。

    Returns:
        解码后的图片字节。

    Raises:
        OcrError: 前缀格式非法、base64 解码失败或解码结果为空；错误消息
            不回显原始输入，避免把超大/敏感 payload 泄露到日志或终端。
    """
    if payload.startswith(_DATA_URI_PREFIX):
        _, sep, payload = payload.partition(",")
        if not sep:
            raise OcrError("图片 base64 解码失败")
    payload = "".join(payload.split())
    if not payload:
        raise OcrError("图片输入为空")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except ValueError as exc:
        raise OcrError("图片 base64 解码失败") from exc
    if not decoded:
        raise OcrError("图片输入为空")
    return decoded


def _coerce_image(image: bytes | str) -> bytes:
    """把识别入参归一化为图片原始字节。

    Args:
        image: 图片原始字节，或 base64 字符串（兼容 ``data:...;base64,`` 前缀）。

    Returns:
        图片原始字节。

    Raises:
        OcrError: 输入为空、类型不支持或 base64 解码失败。
    """
    raw: object = image
    if isinstance(raw, bytes):
        if not raw:
            raise OcrError("图片输入为空")
        return raw
    if not isinstance(raw, str):
        raise OcrError(f"不支持的图片输入类型: {type(raw).__name__}")
    return _decode_base64(raw)


def _close_engine(engine: OCREngine) -> None:
    """尽力释放引擎资源，兼容未实现 ``close`` 的替代实现（如测试 Fake）。

    Args:
        engine: 引擎实例。
    """
    close = getattr(engine, "close", None)
    if callable(close):
        close()


def _resolve_path(path: str, base_dir: Path) -> Path:
    """将模型路径解析为绝对路径。

    Args:
        path: 配置文件中的路径（相对或绝对）。
        base_dir: 配置文件所在目录，用于解析相对路径。

    Returns:
        解析后的绝对路径。
    """
    p = Path(path)
    return p if p.is_absolute() else (base_dir / p).resolve()


class OCRManager:
    """OCR 模块管理器。

    Args:
        config_manager: 通用配置中心实例（用于读取 OCR 配置并支持热更新）。

    Examples:
        >>> with OCRManager(config_manager) as manager:
        ...     result = manager.recognize(b"image-bytes")
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager
        self._engines: dict[ModelSpec, OCREngine] = {}
        self._active_spec: ModelSpec | None = None
        self._mode: ModelMode | None = None
        self._default_spec: ModelSpec | None = None
        self._device: DevicePlan | None = None
        self._thresholds: OcrThresholdConfig | None = None
        self._model_paths: dict[ModelSpec, ModelSpecPaths] | None = None
        self._apply_config(force=True)

    def _apply_config(self, force: bool = False) -> None:
        """读取最新配置，若模式 / 默认规格 / 设备 / 阈值变化则原子重建引擎。

        重建时先在局部变量中构建全部新引擎，全部成功后才一次性替换
        ``self._engines`` / ``self._active_spec`` 等状态；任一失败时旧引擎与
        旧状态完全保留，异常包装为 :class:`OcrEngineError`。

        Args:
            force: 是否强制重建。

        Raises:
            OcrEngineError: 引擎重建失败（含 GPU 回退 CPU 仍失败）。
        """
        ocr_cfg = self._config_manager.ocr()
        mode = ocr_cfg.model.mode
        default_spec = ocr_cfg.model.default_spec
        device = resolve_device()

        changed = (
            force
            or mode != self._mode
            or default_spec != self._default_spec
            or device != self._device
            or ocr_cfg.thresholds != self._thresholds
            # 模型路径也要参与比较：只改 config.yaml 里的 det/rec/dict 路径而不动
            # mode 时，旧引擎会静默继续跑旧模型，用户以为换模型成功了。
            or ocr_cfg.model.models != self._model_paths
        )
        if not changed:
            return

        try:
            new_engines, new_active = self._build_engines(mode, device, ocr_cfg)
        except Exception as exc:
            logger.exception("OCR 引擎重建失败")
            raise OcrEngineError(f"OCR 引擎重建失败: {exc}") from exc
        # 全部构建成功后才原子替换状态，失败不污染旧引擎
        self._engines = new_engines
        self._active_spec = new_active
        self._mode = mode
        self._default_spec = default_spec
        self._device = device
        self._thresholds = ocr_cfg.thresholds
        self._model_paths = ocr_cfg.model.models
        logger.info("OCR engines rebuilt: mode=%s active=%s", mode, new_active)

    def _build_engines(
        self, mode: ModelMode, device: DevicePlan, ocr_cfg: OcrConfig
    ) -> tuple[dict[ModelSpec, OCREngine], ModelSpec]:
        """构建本次配置所需的全部引擎（只返回局部结果，不修改 ``self``）。

        - 非 ``all``：只加载 ``mode`` 对应的单规格（``default_spec`` 不参与加载）；
        - ``all``：加载 tiny/small/medium 全部档位，生效规格取 ``default_spec``。

        Args:
            mode: 模型模式。
            device: 设备执行计划。
            ocr_cfg: 当前 OCR 配置。

        Returns:
            ``(engines, active_spec)``。

        Raises:
            OcrEngineError: 任一引擎构建失败。
        """
        specs = (
            list(_REQUIRED_SPECS) if mode == ModelMode.ALL else [ModelSpec(mode.value)]
        )
        engines = {spec: self._build_engine(spec, ocr_cfg, device) for spec in specs}
        active = ocr_cfg.model.default_spec if mode == ModelMode.ALL else specs[0]
        return engines, active

    def _build_engine(
        self, spec: ModelSpec, ocr_cfg: OcrConfig, device: DevicePlan
    ) -> OCREngine:
        """构建指定规格的引擎实例。

        模型路径若为相对路径，则基于配置文件所在目录解析为绝对路径，
        以保证无论从何处运行都能正确定位模型文件。

        Args:
            spec: 模型规格。
            ocr_cfg: 当前 OCR 配置。
            device: 设备执行计划。

        Returns:
            构建完成的引擎实例。

        Raises:
            OcrError: 配置中缺少该规格的模型路径（schema 已保证齐全，防御）。
            OcrEngineError: 模型文件缺失或引擎初始化失败。
        """
        paths = ocr_cfg.model.models.get(spec)
        if paths is None:
            raise OcrError(f"模型配置缺失: {spec.value}")
        base_dir = self._config_manager.path.parent
        resolved = ModelSpecPaths(
            det=str(_resolve_path(paths.det, base_dir)),
            rec=str(_resolve_path(paths.rec, base_dir)),
            dict_path=str(_resolve_path(paths.dict_path, base_dir)),
            cls=str(_resolve_path(paths.cls, base_dir)) if paths.cls else None,
        )
        for label, model_path in (
            ("det", resolved.det),
            ("rec", resolved.rec),
            ("dict", resolved.dict_path),
            ("cls", resolved.cls),
        ):
            if model_path and not Path(model_path).exists():
                raise OcrEngineError(f"模型文件不存在 ({label}): {model_path}")
        try:
            return OCREngine(
                spec=spec,
                paths=resolved,
                device=device,
                thresholds=ocr_cfg.thresholds,
            )
        except OcrEngineError:
            raise
        except Exception as exc:
            raise OcrEngineError(f"OCR 引擎({spec.value})初始化失败: {exc}") from exc

    def _ensure_loaded(self, spec: ModelSpec) -> OCREngine:
        """确保目标规格已加载，未加载则按需构建（懒加载，先建后换）。

        Args:
            spec: 目标模型规格。

        Returns:
            对应引擎实例。

        Raises:
            OcrError: 设备状态缺失。
            OcrEngineError: 目标引擎构建失败（现有引擎不受影响）。
        """
        engine = self._engines.get(spec)
        if engine is not None:
            return engine
        if self._device is None:
            raise OcrError("OCR 引擎尚未初始化设备")
        new_engine = self._build_engine(spec, self._config_manager.ocr(), self._device)
        # 先建后换：构建成功后再以新字典替换，避免半成品污染现有映射
        self._engines = {**self._engines, spec: new_engine}
        return new_engine

    @property
    def active_spec(self) -> ModelSpec | None:
        """当前生效的模型规格。"""
        return self._active_spec

    def set_model_spec(self, spec: ModelSpec | str) -> None:
        """运行时热切换模型规格。

        非 ``all`` 模式先构建新引擎再替换（失败时旧引擎与 ``active_spec``
        保持不变），并释放旧实例；``all`` 模式按需懒加载目标规格。

        Args:
            spec: 目标规格（``ModelSpec`` 枚举或字符串 ``tiny/small/medium``）。

        Raises:
            OcrError: 指定了非法规格（含把 ``all`` 当规格）。
            OcrEngineError: 目标引擎构建失败（旧状态不变）。
        """
        self._apply_config()
        target = _coerce_spec(spec)

        if self._mode == ModelMode.ALL:
            self._ensure_loaded(target)
        elif target != self._active_spec:
            if self._device is None:
                raise OcrError("OCR 引擎尚未初始化设备")
            new_engine = self._build_engine(
                target, self._config_manager.ocr(), self._device
            )
            old_engines = self._engines
            self._engines = {target: new_engine}
            for engine in old_engines.values():
                _close_engine(engine)
        self._active_spec = target
        logger.info("OCR model spec switched to: %s", target.value)

    def recognize(self, image: bytes | str) -> OCRResult:
        """识别单张图片。

        Args:
            image: 图片原始字节，或 base64 字符串（兼容 ``data:...;base64,``
                前缀并忽略空白字符）。

        Returns:
            结构化识别结果。

        Raises:
            OcrError: 输入非法、引擎未加载或识别失败；``_apply_config`` 与
                引擎调用的非业务异常统一归一化为此异常。
            OcrEngineError: 引擎重建失败（配置热更新触发；``OcrError`` 子类）。
        """
        image_bytes = _coerce_image(image)
        try:
            self._apply_config()
            engine = self._engines.get(self._active_spec) if self._active_spec else None
            if engine is None:
                raise OcrError("OCR 引擎未加载")
            items, elapsed = engine.recognize(image_bytes)
        except OcrError:
            raise
        except Exception as exc:
            logger.exception("OCR 识别失败")
            raise OcrError("OCR 识别失败") from exc
        return OCRResult(items=items, elapsed=elapsed)

    def close(self) -> None:
        """释放全部引擎资源。

        清空引擎字典并复位生效规格；保留模式 / 设备状态，关闭后调用
        :meth:`recognize` 抛 ``OcrError``（不会隐式重建）。兼容未实现
        ``close`` 的替代引擎实现，重复调用安全。
        """
        for engine in self._engines.values():
            _close_engine(engine)
        self._engines = {}
        self._active_spec = None

    def __enter__(self) -> "OCRManager":
        """进入上下文，返回管理器自身。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """退出上下文时释放引擎资源。"""
        self.close()
