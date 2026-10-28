"""聚合各功能子应用，供主应用挂载。

扩容约定：新增功能时在 ``commands/`` 下新建模块定义 ``Typer`` 子应用，
在此导入并加入 :data:`__all__`，再在 :mod:`cli.app` 中 ``add_typer`` 挂载。
"""

from cli.commands.config import config_app
from cli.commands.ocr import ocr_cmd

__all__ = ["config_app", "ocr_cmd"]
