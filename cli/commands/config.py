"""配置子命令：接入 :class:`ConfigManager`，读写 ``config.yaml`` 并触发热更新。

命令是薄壳：只做参数解析、调 service 层、格式化输出，不承载业务逻辑。

路径契约：本命令的“点路径”基于 **OCR 配置段内部**（如 ``model.mode``），
不是顶层 ``ocr.model.mode``——与 GUI / 配置 schema 的字段层级保持一致。
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from app.bootstrap import build_config_manager, default_config_path
from common.exceptions import ConfigError
from config.defaults import ocr_defaults_update

if TYPE_CHECKING:  # 仅类型检查时导入，保持 `import cli.app` 轻量
    from config.manager import ConfigManager

__all__ = ["config_app"]

config_app = typer.Typer(help="配置读写命令")

_HELP_PATH = "点路径，如 model.mode（相对 ocr 段）"

_MISSING = object()
"""路径不存在哨兵；用于区分“路径不存在”与合法的 ``None`` 值。"""


def _resolve_config(config: Path | None) -> Path:
    return config if config is not None else default_config_path()


def _parse_value(text: str) -> object:
    """把字符串参数解析为 ``bool`` / ``int`` / ``float`` / ``str``。"""
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def _nested_update(path: str, value: object) -> dict[str, object]:
    """点路径转嵌套 update（如 model.mode -> {'model': {'mode': ...}}）。"""
    parts = path.strip().split(".")
    update: dict[str, object] = {}
    node = update
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            node[part] = value
        else:
            child: dict[str, object] = {}
            node[part] = child
            node = child
    return update


def _get_by_path(data: dict[str, object], path: str) -> object:
    """按点路径在配置字典中导航取值，不存在时返回 :data:`_MISSING`。"""
    node: object = data
    for part in path.strip().split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _print_dict(data: dict[str, object], indent: int = 0) -> None:
    """以缩进文本打印嵌套配置。"""
    pad = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            typer.echo(f"{pad}{key}:")
            _print_dict(value, indent + 1)
        else:
            typer.echo(f"{pad}{key}: {value}")


def _emit(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_dict(payload)


def _open_config(
    config: Path | None,
) -> "tuple[ConfigManager, dict[str, object]]":
    """构建配置中心并读取当前 OCR 配置；配置无效时友好报错并退出码 2。

    Args:
        config: ``--config`` 指定的配置文件路径；缺省使用默认路径。

    Returns:
        ``(配置中心, 当前 OCR 配置的 JSON 化字典)``。

    Raises:
        typer.Exit: 配置读取 / 校验失败（退出码 ``2``）。
    """
    try:
        manager = build_config_manager(_resolve_config(config))
        data = manager.ocr().model_dump(mode="json")
    except ConfigError as exc:
        typer.echo(f"配置读取失败: {exc}", err=True)
        raise typer.Exit(2) from exc
    return manager, data


@config_app.command("get")
def config_get(
    path: Annotated[str | None, typer.Argument(help=_HELP_PATH)] = None,
    json_output: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """查看当前生效配置（缺省显示全部）。"""
    _manager, data = _open_config(config)
    if path:
        value = _get_by_path(data, path)
        if value is _MISSING:
            typer.echo(f"配置项不存在: {path}", err=True)
            raise typer.Exit(2)
        _emit({path: value}, json_output)
    else:
        _emit(data, json_output)


@config_app.command("list")
def config_list(
    json_output: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """列出全部当前生效配置。"""
    config_get(None, json_output=json_output, config=config)


@config_app.command("set")
def config_set(
    path: Annotated[str, typer.Argument(help=_HELP_PATH)],
    value: Annotated[str, typer.Argument(help="值（自动解析 bool/int/float/str）")],
    json_output: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """修改配置并触发配置中心热更新。"""
    manager, data = _open_config(config)
    if _get_by_path(data, path) is _MISSING:
        # 只允许修改已存在的配置项：拼写错误显式报错，且不触碰配置文件
        typer.echo(f"配置项不存在: {path}", err=True)
        raise typer.Exit(2)
    update = _nested_update(path, _parse_value(value))
    try:
        manager.save_ocr(update)
    except ConfigError as exc:
        # save_ocr 为原子写（临时文件回读校验后替换），失败时原配置文件保持不变
        typer.echo(f"配置写入失败: {exc}", err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(json.dumps(update, ensure_ascii=False))
    else:
        typer.echo(f"已更新 {path} = {value}，配置中心已重载")


@config_app.command("reset")
def config_reset(
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """恢复 schema 默认值（模型路径保留当前）。"""
    manager, _data = _open_config(config)
    try:
        manager.save_ocr(ocr_defaults_update())
    except ConfigError as exc:
        typer.echo(f"配置恢复失败: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo("已恢复默认值，配置中心已重载")
