"""OCR 管理器：模块对外统一入口。

职责：
- 按配置的模型模式（``tiny/small/medium/all``）加载引擎；
- **资源控制**：非 ``all`` 模式只同时加载一个规格实例，切换时释放旧实例；
- **规格热切换**：``set_model_spec`` 运行时切换，无需重启；
- **配置热更新**：识别前检测配置变化（设备 / 模式），变化后自动重建引擎。

对外接口：``recognize(image: bytes | str) -> OCRResult``（字节流 / base64 输入、
结构化输出）。
"""

import base64
import logging
from pathlib import Path

from common.exceptions import OcrEngineError, OcrError
from config.manager import ConfigManager
from config.schema import ModelMode, ModelSpec, ModelSpecPaths, OcrConfig
from service.ocr.device import DevicePlan, resolve_device
from service.ocr.engine import OCREngine
from service.ocr.models import OCRResult

logger = logging.getLogger(__name__)

_REQUIRED_SPECS = (ModelSpec.TINY, ModelSpec.SMALL, ModelSpec.MEDIUM)
_CPU_PLAN = DevicePlan()


def _coerce_spec(spec: ModelSpec | str) -> ModelSpec:
    """把 ``ModelSpec`` 或字符串转换为合法规格，非法值抛 ``OcrError``。"""
    if isinstance(spec, str):
        if spec == ModelMode.ALL.value:
            raise OcrError("'all' 是 model.mode 取值，不能作为模型规格")
        try:
            return ModelSpec(spec)
        except ValueError:
            raise OcrError(f"非法的模型规格: {spec}") from None
    if not isinstance(spec, ModelSpec):
        raise OcrError(f"非法的模型规格: {spec}")
    return spec


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
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager
        self._engines: dict[ModelSpec, OCREngine] = {}
        self._active_spec: ModelSpec | None = None
        self._mode: ModelMode | None = None
        self._device: DevicePlan | None = None
        self._apply_config(force=True)

    def _apply_config(self, force: bool = False) -> None:
        """读取最新配置，若设备 / 模式变化则重建引擎（失败回滚，不污染状态）。

        Args:
            force: 是否强制重建。

        Raises:
            OcrEngineError: 引擎重建失败（含 GPU 降级 CPU 仍失败）。
        """
        ocr_cfg = self._config_manager.ocr()
        mode = ocr_cfg.model.mode
        device = resolve_device(ocr_cfg.device.gpu_enabled)

        changed = force or mode != self._mode or device != self._device
        if not changed:
            return

        try:
            new_engines, new_active, used_device = self._build_all(
                mode, device, ocr_cfg
            )
        except Exception as exc:
            # 构建失败：包装为 OcrEngineError，且不替换旧状态（保持旧引擎可用）
            raise OcrEngineError(f"OCR 引擎重建失败: {exc}") from exc
        # 全部构建成功后才原子替换状态，失败不污染旧引擎
        self._engines = new_engines
        self._active_spec = new_active
        self._mode = mode
        self._device = used_device
        logger.info("OCR engines rebuilt: mode=%s active=%s", mode, new_active)

    def _build_all(
        self, mode: ModelMode, device: DevicePlan, ocr_cfg: OcrConfig
    ) -> tuple[dict[ModelSpec, OCREngine], ModelSpec, DevicePlan]:
        """构建全部引擎；GPU 初始化失败自动降级 CPU 重试。

        Returns:
            ``(engines, active_spec, used_device)``。
        """
        specs = (
            list(_REQUIRED_SPECS) if mode == ModelMode.ALL else [ModelSpec(mode.value)]
        )
        try:
            engines = {
                spec: self._build_engine(spec, ocr_cfg, device) for spec in specs
            }
        except Exception as exc:
            if device.device_name == "cpu":
                raise
            # GPU 后端存在但初始化失败（驱动/模型不兼容）：降级 CPU 重建一次
            logger.warning("GPU 引擎初始化失败 (%s)，自动回退 CPU", exc, exc_info=True)
            engines = {
                spec: self._build_engine(spec, ocr_cfg, _CPU_PLAN) for spec in specs
            }
            device = _CPU_PLAN
        active = self._pick_active(mode, ocr_cfg, engines)
        return engines, active, device

    def _pick_active(
        self, mode: ModelMode, ocr_cfg: OcrConfig, engines: dict[ModelSpec, OCREngine]
    ) -> ModelSpec:
        """确定生效规格：all 模式优先用 default_spec，否则取首个。"""
        if mode == ModelMode.ALL and ocr_cfg.model.default_spec in engines:
            return ocr_cfg.model.default_spec
        return next(iter(engines))

    def _build_engine(
        self, spec: ModelSpec, ocr_cfg: OcrConfig, device: DevicePlan
    ) -> OCREngine:
        """构建指定规格的引擎实例；先校验模型文件存在，再创建引擎。

        模型路径若为相对路径，则基于配置文件所在目录解析为绝对路径，
        以保证无论从何处运行都能正确定位模型文件。

        Raises:
            OcrEngineError: 模型文件缺失或引擎初始化失败。
        """
        paths = ocr_cfg.model.models[spec]
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
        except Exception as exc:
            raise OcrEngineError(f"OCR 引擎({spec.value})初始化失败: {exc}") from exc

    def _ensure_loaded(self, spec: ModelSpec) -> OCREngine:
        """确保目标规格已加载，未加载则按需构建（懒加载）。"""
        engine = self._engines.get(spec)
        if engine is None:
            if self._device is None:
                raise OcrError("OCR 引擎尚未初始化设备")
            engine = self._build_engine(spec, self._config_manager.ocr(), self._device)
            self._engines[spec] = engine
        return engine

    @property
    def active_spec(self) -> ModelSpec | None:
        """当前生效的模型规格。"""
        return self._active_spec

    def set_model_spec(self, spec: ModelSpec | str) -> None:
        """运行时热切换模型规格。

        Args:
            spec: 目标规格（``ModelSpec`` 枚举或字符串 ``tiny/small/medium``）。

        Raises:
            OcrError: 指定了非法规格（含把 ``all`` 当规格）。
            OcrEngineError: 目标引擎加载失败。
        """
        self._apply_config()
        target = _coerce_spec(spec)

        if self._mode != ModelMode.ALL and target != self._active_spec:
            # 单规格模式：只保留一个实例，切换时释放旧实例
            if self._device is None:
                raise OcrError("OCR 引擎尚未初始化设备")
            new_engine = self._build_engine(
                target, self._config_manager.ocr(), self._device
            )
            self._engines = {target: new_engine}
        else:
            self._ensure_loaded(target)
        self._active_spec = target
        logger.info("OCR model spec switched to: %s", target.value)

    def recognize(self, image: bytes | str) -> OCRResult:
        """识别单张图片。

        Args:
            image: 图片原始字节，或 base64 编码的字符串。

        Returns:
            结构化识别结果。

        Raises:
            OcrError: 输入非法、未加载引擎或识别失败。
            OcrEngineError: 引擎重建失败（配置热更新触发）。
        """
        if isinstance(image, str):
            try:
                image = base64.b64decode(image, validate=True)
            except Exception:  # noqa: BLE001 - 有意归一化所有解码失败为 OcrError
                raise OcrError("非法输入：支持图片字节或 base64 字符串") from None
            if not image:
                raise OcrError("base64 解码结果为空")

        self._apply_config()
        engine = self._engines.get(self._active_spec) if self._active_spec else None
        if engine is None:
            raise OcrError("OCR 引擎尚未加载")
        try:
            items, elapsed = engine.recognize(image)
        except (OcrError, OcrEngineError):
            raise
        except Exception as exc:
            raise OcrError(f"OCR 识别失败: {exc}") from exc
        return OCRResult(items=items, elapsed=elapsed)

    def close(self) -> None:
        """释放全部引擎资源（置空引用，提示 GC 回收）。"""
        for engine in self._engines.values():
            engine.close()
        self._engines.clear()
        self._active_spec = None
