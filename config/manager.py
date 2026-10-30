"""通用配置中心。

职责：
- 从 YAML 加载并校验配置（见 :mod:`config.loader`）；
- 缓存配置对象，供各模块读取；
- **运行时热更新**：检测配置文件变更后自动重载，无需重启；
- **线程安全**：读写用 ``RLock`` 串行化，写回为原子替换，避免并发读到半截文件。

各模块通过 :meth:`ConfigManager.get` / :meth:`ConfigManager.ocr` 获取配置，
不直接访问文件，保证单一配置来源。
"""

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from common.exceptions import ConfigError
from config.loader import load_config
from config.schema import AppConfig, AppSettingsConfig, OcrConfig

logger = logging.getLogger(__name__)

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

        重载失败时保留上一次成功的配置缓存（``_config`` 与 ``_mtime`` 均不
        更新），记录告警后原样抛出，避免调用方读到半新半旧的配置。

        Raises:
            ConfigError: 配置读取或校验失败。
            OSError: 配置文件状态读取失败。
        """
        with self._lock:
            try:
                config = load_config(self.path)
                mtime = self.path.stat().st_mtime_ns
            except (ConfigError, OSError):
                logger.warning("config reload failed: %s", self.path, exc_info=True)
                raise
            self._config = config
            self._mtime = mtime

    def _refresh_if_changed(self) -> bool:
        """检测配置变更，若文件被修改则热更新重载。

        文件在 ``exists()`` 与 ``stat()`` 之间被删除时（TOCTOU），视作未变化
        返回 False，避免把 ``FileNotFoundError`` 泄漏给配置读取方。

        Returns:
            是否发生了重载。
        """
        with self._lock:
            if not self.path.exists():
                return False
            try:
                new_mtime = self.path.stat().st_mtime_ns
            except OSError:
                return False
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
        "临时文件 → 回读校验 → 备份 → 原子替换 → 重载" 流程，任何一步失败
        都不改变原 config.yaml。

        Args:
            update: 要更新的 OCR 配置字段，支持嵌套字典，如
                ``{"model": {"mode": "tiny"}}``。

        Raises:
            ConfigError: 合并后的 OCR 配置不合法、或读回校验失败。
            OSError: 配置文件读写失败。
        """
        self._write_section("ocr", OcrConfig, update)

    def save_app(self, update: dict[str, object]) -> None:
        """写回程序级偏好字段（如 ``app.ui_language``）到 config.yaml。

        语义与 :meth:`save_ocr` 相同（round-trip、schema 校验、原子写回），
        针对 ``app`` 段。

        Args:
            update: 要更新的程序偏好字段，支持嵌套字典，如
                ``{"ui_language": "zh_CN"}``。

        Raises:
            ConfigError: 合并后的程序偏好配置不合法、或读回校验失败。
            OSError: 配置文件读写失败。
        """
        self._write_section("app", AppSettingsConfig, update)

    def _write_section(
        self, section: str, model_cls: type[BaseModel], update: dict[str, object]
    ) -> None:
        """将 ``update`` 深度合并写入指定顶层配置段，并原子写回。

        流程与失败语义与 :meth:`save_ocr` 描述一致；``section`` 为顶层段名，
        ``model_cls`` 用于校验合并结果（``extra="forbid"`` 拒绝未知键）。

        Args:
            section: 顶层配置段名（如 ``ocr`` / ``app``）。
            model_cls: 该段的 pydantic 模型，用于写回前校验。
            update: 待合并字段，支持嵌套字典。
        """
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                data = _yaml.load(f)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ConfigError(f"配置文件顶层必须是映射结构，拒绝写入: {self.path}")
            section_data = data.get(section)
            if not isinstance(section_data, dict):
                section_data = {}
                data[section] = section_data
            _deep_merge(section_data, update)
            # 先用副本校验合并结果，未知键（extra=forbid）/非法值在此拦截
            try:
                model_cls.model_validate(dict(section_data))
            except ValidationError as exc:
                raise ConfigError(f"配置校验失败: {self.path}: {exc}") from exc
            self._atomic_write(data)

    def _atomic_write(self, data: dict[Any, Any]) -> None:
        """原子写回完整配置，任何失败都不破坏原文件。

        流程：写同目录临时文件 → ``load_config`` 回读校验 → 备份旧文件为
        ``<name>.bak`` → ``os.replace`` 原子替换 → 重载。临时文件失败时清理；
        已替换后重载失败时用备份回滚，保证 config.yaml 不会停留在半写状态。

        Args:
            data: 待写回的完整配置映射（round-trip 结构，保留注释与键顺序）。

        Raises:
            ConfigError: 回读校验失败。
            OSError: 文件读写失败。
        """
        bak_path = self.path.with_name(self.path.name + ".bak")
        tmp_path: Path | None = None
        replaced = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=self.path.parent,
                suffix=".tmp",
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                _yaml.dump(data, tmp_file)
            load_config(tmp_path)  # 回读校验，保证落盘内容与正常加载语义一致
            if self.path.exists():
                shutil.copy2(self.path, bak_path)
            os.replace(tmp_path, self.path)
            tmp_path = None  # 已原子替换，临时文件不再存在
            replaced = True
            self.reload()
        except BaseException:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            if replaced:
                self._restore_backup(bak_path)
            raise

    def _restore_backup(self, bak_path: Path) -> None:
        """用备份回滚已替换的配置文件（仅在替换后重载失败时调用）。

        回滚失败只记录告警，不掩盖触发回滚的原始异常。

        Args:
            bak_path: 旧配置备份路径。
        """
        if not bak_path.exists():
            return
        try:
            os.replace(bak_path, self.path)
        except OSError:
            logger.warning("config rollback failed: %s", self.path, exc_info=True)

    def ocr(self) -> OcrConfig:
        """获取 OCR 模块配置。

        Returns:
            OCR 配置对象。
        """
        return self.get().ocr

    def app(self) -> AppSettingsConfig:
        """获取程序级偏好配置。

        Returns:
            程序级偏好配置对象（含界面语言等）。
        """
        return self.get().app
