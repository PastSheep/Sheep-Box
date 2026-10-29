"""配置子命令：接入 :class:`ConfigManager`，读写 ``config.yaml`` 并触发热更新。

命令是薄壳：只做参数解析、调 service 层、格式化输出，不承载业务逻辑。

路径契约：本命令的“点路径”基于 **OCR 配置段内部**（如 ``model.mode``），
不是顶层 ``ocr.model.mode``——与 GUI / 配置 schema 的字段层级保持一致。
"""

import json
from pathlib import Path
from typing import Annotated

import typer

from app.bootstrap import build_config_manager, default_config_path
from config.schema import ocr_defaults_update

__all__ = ["config_app"]

config_app = typer.Typer(help="配置读写命令")


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
    """按点路径在配置字典中导航取值。"""
    node: object = data
    for part in path.strip().split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
        if node is None:
            return None
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


@config_app.command("get")
def config_get(
    path: Annotated[
        str | None,
        typer.Argument(help="点路径（相对 OCR 段），如 model.mode；缺省显示全部"),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """查看当前生效配置。"""
    cm = build_config_manager(_resolve_config(config))
    data = cm.ocr().model_dump(mode="json")
    if path:
        value = _get_by_path(data, path)
        if value is None:
            typer.echo(f"错误: 配置路径不存在: {path}", err=True)
            raise SystemExit(2)
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
    path: Annotated[str, typer.Argument(help="点路径（相对 OCR 段），如 model.mode")],
    value: Annotated[str, typer.Argument(help="值（自动解析 bool/int/float/str）")],
    json_output: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """修改配置并触发配置中心热更新。"""
    cm = build_config_manager(_resolve_config(config))
    update = _nested_update(path, _parse_value(value))
    cm.save_ocr(update)
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
    cm = build_config_manager(_resolve_config(config))
    cm.save_ocr(ocr_defaults_update())
    typer.echo("已恢复默认值，配置中心已重载")
