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

> **GPU 加速（首版 Windows，自动探测）**：程序启动时自动探测可用推理后端
> （Windows 优先 DirectML，其次 CUDA），有可用后端即启用，探测失败自动回退 CPU。
> 需按部署平台安装对应后端。CPU 包与 GPU 包**互斥**，dml / cuda **二选一，禁止同时安装**。
>
> 注意 pip 的 extras 是**并集**而非替换：安装 GPU extra 会同时装上 base 的 CPU
> `onnxruntime`，而 `onnxruntime` / `onnxruntime-directml` / `onnxruntime-gpu`
> 提供**同名顶层模块**，并存会互相覆盖、行为不可预期。安装 GPU extra 后必须
> 卸载 CPU 包（或使用干净环境只装 GPU 包）：
>
> ```bash
> # Windows：支持 AMD / NVIDIA / Intel 显卡（优先 DirectML，探测失败回退 CPU）
> pip install -e ".[dev,ocr-gpu-dml]"
> pip uninstall -y onnxruntime  # 必须：CPU 包与 GPU 包互斥，避免同名模块冲突
>
> # Linux / NVIDIA：CUDA 后端（与 DirectML 二选一）
> pip install -e ".[dev,ocr-gpu-cuda]"
> pip uninstall -y onnxruntime
> ```
>
> 未安装 GPU 后端或探测失败时，程序自动回退 CPU（内部处理，无需手动配置）。

## 目录结构

```text
config/         配置文件与配置中心（pydantic 校验、原子写回、mtime 热重载）
common/         公共工具、常量、异常
service/        核心业务逻辑（service/ocr 为 OCR 模块，含 postprocess 后处理工具）
gui/            桌面界面（PySide6）：设置页承载程序级偏好（界面语言 / 黑白主题）
cli/            CLI 入口（ocr 识别 / config 读写）
app/            组装根（bootstrap）、日志配置、i18n、主题
models/         数据模型（预留）
api/            接口入口（预留）
tests/          单元测试
assets/         ocr/ 模型资源（onnx 不入库）；i18n/ 界面翻译（.ts / .qm）
main.py         项目启动入口
```

## 配置结构（config/config.yaml）

```yaml
ocr:                 # 业务模块配置（当前唯一模块）
  model:
    mode: small      # 启动加载方式：tiny / small / medium / all
    default_spec: small  # all 模式下的默认生效规格（非 all 时由 mode 决定档位）
    models:          # tiny / small / medium 三档 det / rec / dict / cls 路径（必填）
      tiny: {...}
  thresholds:        # text_score / box_thresh（0~1）、unclip_ratio（>0）
    text_score: 0.5
  language: zh       # 识别语言，中文优先
app:                 # 程序级偏好（由设置界面承载）
  ui_language: zh_CN # 界面语言（i18n）
  theme: light       # 界面主题：light / dark
```

- 所有段均 `extra="forbid"`：未知键、越界阈值、模型缺档在加载时直接报错，不会静默写坏配置；
- 写回为原子操作：临时文件回读校验 → 旧文件备份 `.bak` → 替换；失败时原文件保持不变。

## OCR 模块

仅实现"识别 + 结构化输出"（字节流 / base64 输入），**不做文本清洗 / 后处理**；
需要清洗、去重、多栏合并的，由消费结构化结果的业务模块自行实现（可复用下方后处理工具）。

```python
from config.manager import ConfigManager
from service.ocr import OCRManager

manager = OCRManager(ConfigManager("config/config.yaml"))

# 字节流 / base64 输入 → 结构化结果（base64 支持 "data:image/png;base64,..." 前缀）
result = manager.recognize(image_bytes)   # bytes 或 base64 字符串
result.items                              # [OCRTextItem(text, bbox, score)]
result.text                               # 按识别顺序拼接的纯文本

# 模型规格热切换（tiny / small / medium）
manager.set_model_spec("tiny")
```

- 模型加载：`ocr.model.mode` 决定启动加载方式（默认 `small`）。非 `all` 时只加载 `mode`
  对应的单档实例；`all` 时三档全载，生效规格取 `default_spec`；
- 规格热切换：`set_model_spec` 先建新引擎再替换，失败时旧引擎与生效规格保持不变；
  配置变更触发重建失败会保留旧状态（原子替换），不会进入半可用状态；
- 设备：无用户开关，启动自动探测 GPU（DirectML → CUDA）+ CPU 回退（`service/ocr/device.py`）；
- 配置热更新：修改 `config/config.yaml` 后自动生效（mtime 检测），引擎按新配置重建。

### 后处理工具（供消费方复用，不在识别链路内）

`service.ocr.postprocess` 为纯函数工具，`OCRManager` 不调用：

- `sort_into_lines(items)`：按框顶 + 框底共同判行（同一排不同高也能归对），行内按中心 x 升序、行间按行顶升序；
- `clean_whitespace(text)`：空格 / 换行 / 制表 / 全角空格归一为单空格；
- `normalize_chars(text)`：全角字母数字 → 半角，中文全角标点保留。

## GUI 与 CLI 入口

### GUI（PySide6 桌面界面）

设置页承载**程序级偏好**（`app` 配置段），切换立即生效并写回 `config.yaml`：

- 界面语言：`zh_CN` / `en`（Qt 标准 i18n，翻译源文件 `assets/i18n/zh_CN.ts`，当前只维护 `zh_CN`）；
- 界面主题：浅色 / 深色。基于 `QPalette` 切换，并固定 `Fusion` 样式——Windows 原生
  `windowsvista` 样式按系统主题绘制控件、不读应用调色板，不固定样式时深色主题不生效。

OCR 等业务模块的运行参数不在 GUI 中编辑（`model.mode` / `thresholds` 等应由真正消费
OCR 的业务模块控制），当前通过 `config.yaml` 或 CLI 调整。

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

# 配置读写：点路径相对 ocr 段（如 model.mode，不是 ocr.model.mode）
python -m cli config get model.mode [--json]
python -m cli config set model.mode tiny
python -m cli config list [--json]
python -m cli config reset
```

## 开发校验

pre-commit 钩子在提交时自动执行以下检查（也可手动运行）：

```bash
pytest            # 单元测试
ruff check .      # 静态检查
black --check .   # 格式检查
mypy .            # 类型检查（含 tests/）
```

## 开发规范

开发请严格遵守 `docs/开发规范/` 下的三份规范：

- Python 项目编程规范
- 项目 Git 协作规范
- 项目日志 Logger 约定规范
