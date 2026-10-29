"""CLI 主应用：聚合各功能命令与子应用。

扩容：新增功能时在 :mod:`cli.commands` 导出其命令函数或 ``Typer`` 子应用，
在此以 ``app.command(...)`` 或 ``app.add_typer(...)`` 一行挂载即可。
"""

import typer

from app.logging_config import setup_logging
from cli.commands import config_app, ocr_cmd
from common.exceptions import SheepBoxError

app = typer.Typer(
    help="Sheep Box CLI",
    no_args_is_help=True,
    add_completion=False,
)

# ocr 为顶层命令：python -m cli ocr <image>
app.command("ocr")(ocr_cmd)
# config 为子应用：python -m cli config get/set/list/reset
app.add_typer(config_app, name="config")


def run() -> None:
    """CLI 入口：初始化日志并执行，业务异常以错误信息 + 非零退出码结束。"""
    setup_logging()
    try:
        app()
    except typer.Exit:
        raise
    except SheepBoxError as exc:
        typer.echo(f"错误: {exc}", err=True)
        raise SystemExit(1) from exc
    except Exception as exc:
        typer.echo(f"未预期错误: {exc}", err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    run()
