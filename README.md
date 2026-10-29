# Sheep Box

Sheep Box 项目。

## 环境要求

- Python 3.11+（开发工具链与 onnxruntime-directml 均要求 3.11+）
- 虚拟环境：`python -m venv .venv`

## 安装

```bash
# 激活虚拟环境（Windows）
.venv\Scripts\activate

# 安装开发依赖（含 black / ruff / mypy / pre-commit / pytest）
pip install -e ".[dev]"

# 安装 pre-commit 钩子
pre-commit install
```

> **GPU 加速（首版 Windows，默认启用）**：默认开启 GPU（DirectML），
> 需按部署平台安装对应后端（替换默认 CPU onnxruntime）：
>
> ```bash
> # Windows：支持 AMD / NVIDIA / Intel 显卡（DirectML，默认启用）
> pip install -e ".[ocr-gpu-dml]"
> # Linux / NVIDIA：CUDA 后端
> pip install -e ".[ocr-gpu-cuda]"
> ```
>
> 未安装 GPU 后端或探测失败时，程序自动回退 CPU（内部处理，无需手动配置）。

## 目录结构

```text
config/         配置文件、环境配置（含通用配置中心）
common/         公共工具、常量、异常、通用方法
service/        核心业务逻辑（service/ocr 为 OCR 模块）
gui/            桌面设置界面（PySide6，暂不接入 OCR 识别）
cli/            CLI 命令入口（ocr 识别 / config 读写）
models/         数据模型、结构体、ORM 模型
api/            接口入口
tests/          单元测试、集成测试
assets/ocr/     模型资源（大型 onnx 不入库，部署时下载放置）
main.py         项目启动入口
```

## OCR 模块

仅实现模块本体（字节流输入、结构化输出），实际输入输出链路由后续开发接入。

```python
from config.manager import ConfigManager
from service.ocr import OCRManager

manager = OCRManager(ConfigManager("config/config.yaml"))

# 字节流输入 → 结构化结果
result = manager.recognize(image_bytes)   # bytes 或 base64 字符串
result.items                              # [OCRTextItem(text, bbox, score)]
result.text                               # 按行拼接的纯文本

# 模型规格热切换（tiny / small / medium）
manager.set_model_spec("tiny")
```

- 模型规格：PP-OCRv6 `ocr.model.mode`（tiny/small/medium/all），默认 `small`；非 `all` 时只同时加载一个规格实例；
- 设备：`ocr.device.gpu_enabled`（GPU 开关，首版 Windows 默认启用），自动探测 + CPU 回退由程序内部处理；
- 配置热更新：修改 `config/config.yaml` 后自动生效，无需重启。

## GUI 与 CLI 入口

### GUI 设置界面（PySide6）

暂不接入 OCR 识别，提供配置操作入口（"设置"标签页：查看/编辑 OCR 配置并保存，联动配置中心热更新）。

```bash
# 默认启动 GUI（普通用户入口）
python main.py
# 无头模式：不启动 GUI，仅初始化日志后退出
python main.py --no-gui
```

### CLI（typer，可脚本化的无头入口）

```bash
# 单图识别：默认文本输出；--json 输出结构化结果；--spec 热切换规格
python -m cli ocr <图片> [--spec tiny|small|medium] [--json]

# 配置读写：点路径（如 model.mode）；写回后配置中心热更新自动生效
python -m cli config get [path] [--json]
python -m cli config set <path> <value>
python -m cli config list [--json]
python -m cli config reset
```

## 开发规范

开发请严格遵守 `docs/开发规范/` 下的三份规范：

- Python 项目编程规范
- 项目 Git 协作规范
- 项目日志 Logger 约定规范
