"""OCR 子命令：接入 :class:`OCRManager`，实机验证识别链路。

命令是薄壳：只做参数解析、调 service 层、格式化输出，不承载业务逻辑。
"""

import json
from pathlib import Path
from typing import Annotated

import typer

from app.bootstrap import build_ocr_manager, default_config_path
from common.exceptions import ConfigError, OcrError
from config.schema import ModelSpec
from service.ocr.models import OCRResult

__all__ = ["ocr_cmd"]


def _result_to_dict(spec: str, result: OCRResult) -> dict[str, object]:
    """把 ``OCRResult`` 序列化为可 JSON 输出的字典。"""
    return {
        "spec": spec,
        "elapsed": result.elapsed,
        "text": result.text,
        "items": [
            {"text": item.text, "bbox": item.bbox, "score": item.score}
            for item in result.items
        ],
    }


def ocr_cmd(
    image: Annotated[Path, typer.Argument(help="待识别图片路径")],
    spec: Annotated[
        ModelSpec | None, typer.Option("--spec", "-s", help="模型规格（热切换）")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="以 JSON 输出结构化结果")
    ] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置文件路径")
    ] = None,
) -> None:
    """识别单张图片（字节流输入，结构化输出）。

    Raises:
        typer.BadParameter: 图片路径不存在或不是文件。
        typer.Exit: 配置错误或 OCR 流程失败（退出码 1，仅输出友好错误）。
    """
    if not image.is_file():
        raise typer.BadParameter(f"图片路径无效（不存在或不是文件）: {image}")
    cfg = config if config is not None else default_config_path()
    try:
        manager = build_ocr_manager(cfg)
        try:
            if spec is not None:
                manager.set_model_spec(spec)
            result = manager.recognize(image.read_bytes())
            spec_value = (
                spec.value
                if spec is not None
                else (manager.active_spec.value if manager.active_spec else "unknown")
            )
            if json_output:
                typer.echo(
                    json.dumps(
                        _result_to_dict(spec_value, result),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for item in result.items:
                    typer.echo(f"{item.text}  ({item.score:.3f})")
                typer.echo(
                    f"-- 规格={spec_value} 行数={len(result.items)} "
                    f"耗时={result.elapsed:.3f}s"
                )
        finally:
            manager.close()
    except (ConfigError, OcrError) as exc:
        # 只输出友好错误，不打印完整 traceback，也不回显原始 base64 / 图片字节
        typer.echo(f"OCR 失败: {exc}", err=True)
        raise typer.Exit(1) from exc
