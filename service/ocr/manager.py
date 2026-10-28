"""OCR 管理器：模块对外统一入口。

职责：
- 按配置的模型模式（``tiny/small/medium/all``）加载引擎；
- **资源控制**：非 ``all`` 模式只同时加载一个规格实例，切换时释放旧实例；
- **规格热切换**：``set_model_spec`` 运行时切换，无需重启；
- **配置热更新**：识别前检测配置变化（设备 / 模式），变化后自动重建引擎。

对外接口：``recognize(image_bytes) -> OCRResult``（字节流输入、结构化输出）。
"""

import logging
from pathlib import Path

from common.exceptions import OcrError
from config.manager import ConfigManager
from config.schema import ModelMode, ModelSpec, ModelSpecPaths, OcrConfig
from service.ocr.device import DevicePlan, resolve_device
from service.ocr.engine import OCREngine
from service.ocr.models import OCRResult

logger = logging.getLogger(__name__)


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
        self._default_spec: ModelSpec | None = None
        self._device: DevicePlan | None = None
        self._apply_config(force=True)

    def _apply_config(self, force: bool = False) -> None:
        """读取最新配置，若设备 / 模式变化则重建引擎。

        Args:
            force: 是否强制重建。
        """
        ocr_cfg = self._config_manager.ocr()
        mode = ocr_cfg.model.mode
        default_spec = ocr_cfg.model.default_spec
        device = resolve_device(ocr_cfg.device.gpu_enabled)

        changed = (
            force
            or mode != self._mode
            or default_spec != self._default_spec
            or device != self._device
        )
        if not changed:
            return

        self._mode = mode
        self._default_spec = default_spec
        self._device = device
        self._rebuild_engines(mode, default_spec, device, ocr_cfg)

    def _rebuild_engines(
        self,
        mode: ModelMode,
        default_spec: ModelSpec,
        device: DevicePlan,
        ocr_cfg: OcrConfig,
    ) -> None:
        """按当前模式重建全部引擎实例。"""
        self._engines.clear()
        specs = list(ModelSpec) if mode == ModelMode.ALL else [default_spec]
        for spec in specs:
            self._engines[spec] = self._build_engine(spec, ocr_cfg, device)
        self._active_spec = specs[0]
        logger.info(
            "OCR engines rebuilt: mode=%s active=%s", self._mode, self._active_spec
        )

    def _build_engine(
        self, spec: ModelSpec, ocr_cfg: OcrConfig, device: DevicePlan
    ) -> OCREngine:
        """构建指定规格的引擎实例。

        模型路径若为相对路径，则基于配置文件所在目录解析为绝对路径，
        以保证无论从何处运行都能正确定位模型文件。
        """
        paths = ocr_cfg.model.models[spec]
        base_dir = self._config_manager.path.parent
        return OCREngine(
            spec=spec,
            paths=ModelSpecPaths(
                det=str(_resolve_path(paths.det, base_dir)),
                rec=str(_resolve_path(paths.rec, base_dir)),
                cls=str(_resolve_path(paths.cls, base_dir)) if paths.cls else None,
            ),
            device=device,
            thresholds=ocr_cfg.thresholds,
        )

    def _ensure_loaded(self, spec: ModelSpec) -> OCREngine:
        """确保目标规格已加载，未加载则按需构建（懒加载）。"""
        engine = self._engines.get(spec)
        if engine is None:
            device = self._device
            if device is None:
                raise RuntimeError("OCR 引擎尚未初始化设备")
            engine = self._build_engine(spec, self._config_manager.ocr(), device)
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
            OcrError: 指定了非法规格，或当前模式不支持切换到该规格。
        """
        self._apply_config()
        target = ModelSpec(spec) if isinstance(spec, str) else spec
        if target not in ModelSpec:
            raise OcrError(f"非法的模型规格: {spec}")

        if self._mode != ModelMode.ALL and target != self._active_spec:
            # 单规格模式：只保留一个实例，切换时释放旧实例
            device = self._device
            if device is None:
                raise RuntimeError("OCR 引擎尚未初始化设备")
            self._engines.clear()
            self._engines[target] = self._build_engine(
                target, self._config_manager.ocr(), device
            )
        else:
            self._ensure_loaded(target)
        self._active_spec = target
        logger.info("OCR model spec switched to: %s", target.value)

    def recognize(self, image_bytes: bytes) -> OCRResult:
        """识别单张图片字节流。

        Args:
            image_bytes: 图片原始字节。

        Returns:
            结构化识别结果。

        Raises:
            OcrError: 未加载任何引擎或识别失败。
        """
        self._apply_config()
        if self._active_spec is None:
            raise OcrError("OCR 引擎尚未加载")
        engine = self._engines[self._active_spec]
        items, elapsed = engine.recognize(image_bytes)
        return OCRResult(items=items, elapsed=elapsed)
