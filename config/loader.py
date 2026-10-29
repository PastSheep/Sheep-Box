"""配置加载：读取 YAML 并做结构校验。

校验策略：
- **必填严格**：无默认值字段缺失、类型/枚举非法 → 抛出 :class:`ConfigError`；
- **可选回退**：有默认值字段缺失 → 使用默认值。

由 :mod:`config.schema` 的 pydantic 模型承载字段定义与默认值。

读取使用 ruamel YAML（YAML 1.2 语义），与 :mod:`config.manager` 的写回
保持同一 YAML 实现，避免 ``yes/no/on/off`` 等值的 1.1/1.2 解析差异
（详见 git 记录 R-1）。
"""

from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from common.exceptions import ConfigError
from config.schema import AppConfig

_yaml = YAML()


def load_config(config_path: str | Path) -> AppConfig:
    """从 YAML 文件加载并校验完整配置。

    Args:
        config_path: 配置文件路径。

    Returns:
        校验通过的结构化配置对象。

    Raises:
        ConfigError: 文件不存在、YAML 非法、或必填字段缺失/非法。
    """
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"配置文件读取失败: {path} ({exc})") from exc

    try:
        raw = _yaml.load(text)
    except Exception as exc:
        raise ConfigError(f"配置文件 YAML 解析失败: {path} ({exc})") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是映射结构: {path}")

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        # 必填严格：缺失/非法字段直接报错，拒绝以残缺配置启动
        raise ConfigError(f"配置校验失败: {path}: {exc}") from exc
