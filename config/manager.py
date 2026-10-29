"""通用配置中心。

职责：
- 从 YAML 加载并校验配置（见 :mod:`config.loader`）；
- 缓存配置对象，供各模块读取；
- **运行时热更新**：检测配置文件变更后自动重载，无需重启；
- **线程安全**：读写用 ``RLock`` 串行化，写回为原子替换，避免并发读到半截文件。

各模块通过 :meth:`ConfigManager.get` / :meth:`ConfigManager.ocr` 获取配置，
不直接访问文件，保证单一配置来源。
"""

import os
import shutil
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from common.exceptions import ConfigError
from config.loader import load_config
from config.schema import AppConfig, OcrConfig

_yaml = YAML()


def _deep_merge(target: dict[Any, Any], update: dict[Any, Any]) -> None:
    """递归合并 ``update`` 到 ``target``，仅覆盖存在的键。

    嵌套字典逐层合并；非字典值直接覆盖。未提供的字段保持不变。
    """
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


class ConfigManager:
    """项目通用配置中心单实例。

    Args:
        config_path: 配置文件路径（YAML）。

    Attributes:
        path: 配置文件路径（解析为绝对路径）。
    """

    def __init__(self, config_path: str | Path) -> None:
        self.path = Path(config_path).resolve()
        self._config: AppConfig
        self._mtime: int | None = None
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        """强制重新加载并校验配置。

        Raises:
            ConfigError: 配置读取或校验失败。
        """
        with self._lock:
            self._config = load_config(self.path)
            self._mtime = self.path.stat().st_mtime_ns

    def _refresh_if_changed(self) -> bool:
        """检测配置变更，若文件被修改则热更新重载。

        Returns:
            是否发生了重载。
        """
        if not self.path.exists():
            return False
        new_mtime = self.path.stat().st_mtime_ns
        if new_mtime != self._mtime:
            self.reload()
            return True
        return False

    def get(self) -> AppConfig:
        """获取完整配置（访问前自动检测热更新）。

        Returns:
            当前生效的完整配置。
        """
        with self._lock:
            self._refresh_if_changed()
            return self._config

    def save_ocr(self, update: dict[str, object]) -> None:
        """写回 OCR 配置字段到 config.yaml（round-trip，保留注释与结构）。

        仅更新 ``update`` 中提供的字段，未提供的字段保持不变；写回前先用
        schema 校验（``extra="forbid"`` 会拒绝未知键）。写回采用
        "临时文件 → 回读校验 → 原子替换" 流程，失败保留旧文件。

        Args:
            update: 要更新的 OCR 配置字段，支持嵌套字典，如
                ``{"model": {"mode": "tiny"}, "device": {"gpu_enabled": True}}``。

        Raises:
            ConfigError: 合并后的 OCR 配置不合法、或读回校验失败。
            OSError: 配置文件读写失败。
        """
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                data = _yaml.load(f)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ConfigError(f"配置文件顶层必须是映射结构，拒绝写入: {self.path}")
            ocr = data.get("ocr")
            if not isinstance(ocr, dict):
                ocr = {}
                data["ocr"] = ocr
            _deep_merge(ocr, update)
            # 先用副本校验合并结果，未知键（extra=forbid）/非法值在此拦截
            try:
                OcrConfig.model_validate(dict(ocr))
            except ValidationError as exc:
                raise ConfigError(f"配置写回校验失败: {self.path}: {exc}") from exc

            # 原子写：临时文件 → 回读校验 → 备份旧文件 → os.replace
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                with tmp.open("w", encoding="utf-8") as f:
                    _yaml.dump(data, f)
                load_config(tmp)  # 回读校验，语义与最终加载一致
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
            # 备份上一版本（供异常恢复），再原子替换
            try:
                with self.path.open("rb") as src, bak.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            except FileNotFoundError:
                pass
            os.replace(tmp, self.path)
            self.reload()

    def ocr(self) -> OcrConfig:
        """获取 OCR 模块配置。

        Returns:
            OCR 配置对象。
        """
        return self.get().ocr
