"""通用配置中心。

职责：
- 从 YAML 加载并校验配置（见 :mod:`config.loader`）；
- 缓存配置对象，供各模块读取；
- **运行时热更新**：检测配置文件变更后自动重载，无需重启。

各模块通过 :meth:`ConfigManager.get` / :meth:`ConfigManager.ocr` 获取配置，
不直接访问文件，保证单一配置来源。
"""

from pathlib import Path

from config.loader import load_config
from config.schema import AppConfig, OcrConfig


class ConfigManager:
    """项目通用配置中心单实例。

    Args:
        config_path: 配置文件路径（YAML）。

    Attributes:
        path: 配置文件路径。
    """

    def __init__(self, config_path: str | Path) -> None:
        self.path = Path(config_path)
        self._config: AppConfig
        self._mtime: float | None = None
        self.reload()

    def reload(self) -> None:
        """强制重新加载并校验配置。

        Raises:
            ConfigError: 配置读取或校验失败。
        """
        self._config = load_config(self.path)
        stat = self.path.stat()
        self._mtime = stat.st_mtime_ns if hasattr(stat, "st_mtime_ns") else None

    def _refresh_if_changed(self) -> bool:
        """检测配置变更，若文件被修改则热更新重载。

        Returns:
            是否发生了重载。
        """
        if not self.path.exists():
            return False
        stat = self.path.stat()
        new_mtime = stat.st_mtime_ns if hasattr(stat, "st_mtime_ns") else None
        if new_mtime is not None and new_mtime != self._mtime:
            self.reload()
            return True
        return False

    def get(self) -> AppConfig:
        """获取完整配置（访问前自动检测热更新）。

        Returns:
            当前生效的完整配置。
        """
        self._refresh_if_changed()
        return self._config

    def ocr(self) -> OcrConfig:
        """获取 OCR 模块配置。

        Returns:
            OCR 配置对象。
        """
        return self.get().ocr
