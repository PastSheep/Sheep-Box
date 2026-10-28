"""CLI 主应用：聚合各功能命令与子应用。

扩容：新增功能时在 :mod:`cli.commands` 导出其命令函数或 ``Typer`` 子应用，
在此以 ``app.command(...)`` 或 ``app.add_typer(...)`` 一行挂载即可。
"""

import typer

from cli.commands import config_app, ocr_cmd

app = typer.Typer(
    help="Sheep Box CLI",
    no_args_is_help=True,
    add_completion=False,
)

# ocr 为顶层命令：python -m cli ocr <image>
app.command("ocr")(ocr_cmd)
# config 为子应用：python -m cli config get/set/list/reset
app.add_typer(config_app, name="config")


if __name__ == "__main__":
    app()
