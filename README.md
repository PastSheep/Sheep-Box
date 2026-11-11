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
service/        核心能力模块（service/ocr 识别、service/sysinfo 设备资源采集、service/capture 窗口截图）
gui/            桌面界面（PySide6）：设计系统（gui/theme 令牌 / 背景 / 样式 + 组件）+ 导航条 + 页面
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
  status_bar:        # 底部状态栏
    refresh_interval_ms: 1000   # 刷新间隔（500~10000）
    gradient_stops:             # 压力着色锚点（≥2 个，位置不可重复）
      - {at: 0, color: "#17A05E"}
      - {at: 50, color: "#E0A008"}
      - {at: 80, color: "#D94A4A"}
      - {at: 100, color: "#D94A4A"}
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

## 系统信息模块（service/sysinfo）

与 OCR 平级的基础能力模块，只采集**设备级**占用（CPU / 内存 / GPU 利用率），不做业务
判定（不告警、不记历史、不起后台线程）。采样频率由消费方决定，调用即采样。

实现全部走 Windows 原生 API（`ctypes`），**本模块零第三方依赖**，口径与任务管理器一致：

| 指标 | 来源 | 口径 |
|---|---|---|
| CPU | `kernel32!GetSystemTimes` | `(ΔKernel + ΔUser − ΔIdle) / (ΔKernel + ΔUser)`；`KernelTime` 本身已含 `IdleTime`，不减会虚高到 95% |
| 内存 | `kernel32!GlobalMemoryStatusEx` | `used = total − available`（不用整数精度的 `dwMemoryLoad`） |
| GPU | `pdh!\GPU Engine(*)\Utilization Percentage` | WDDM 驱动上报，与厂商无关（NVIDIA / AMD / Intel 都能显示）；同一物理引擎上多进程先求和并截断到 100，再在各引擎间取最大值；不同适配器绝不求和 |
| 适配器目录 | `dxgi!CreateDXGIFactory1 → EnumAdapters1 → GetDesc1` | 排除 `DXGI_ADAPTER_FLAG_SOFTWARE`（WARP / 基础渲染驱动），并按「型号 + 显存容量」去重虚拟显示实例 |

```python
from service.sysinfo import SystemCollector

with SystemCollector() as collector:   # enable_gpu=False 可跳过 GPU 采集
    snapshot = collector.sample()

snapshot.cpu.percent                   # 全核占用 %（距上次采样的区间平均）
snapshot.cpu.logical_cores             # 逻辑处理器数
snapshot.memory.percent                # 物理内存已用 %
snapshot.memory.total / .used / .available
snapshot.gpus                          # tuple[GpuSample]，无可用 GPU 时为空
snapshot.gpus[0].name                  # 适配器型号名（DXGI 提供）
snapshot.gpus[0].utilization_percent   # 适配器级占用 %（最忙引擎）
```

- **差分类计数器**：CPU 与 GPU 都是「距上一次采样」的区间均值，不是瞬时值。构造采集器时
  已建好基线（CPU 时间 + PDH 首采），因此首次 `sample()` 才有意义；紧接着上次采样调用
  （间隔 < 500ms）读数会明显抖动；
- **首帧丢弃**：消费方若用定时器刷新，第一帧应视作基线后立即舍弃，避免显示 0%；
- **适配器目录只枚举一次**：显卡热插拔或驱动重启后需重建 `SystemCollector`；
- **虚拟显示驱动**（Todesk / MuMu / Oray Idd 等）会以物理卡的描述注册额外 LUID，目录按
  「型号 + 显存容量」去重，每个组合只保留一个；同型号同容量的多块真卡会被合并——这一
  场景罕见，且代价只是少显示一项；
- **多卡策略**：每个物理适配器各显示一项（不做「只显示最忙的那块」）；
- **失败边界**：CPU / 内存读不到 → `SystemInfoError`；GPU 计数器不可用或单次读取失败 →
  该次 `gpus` 为空并记 warning，不影响 CPU / 内存。

## 截图模块（service/capture）

与 OCR、sysinfo 平级的基础能力模块：给一个窗口句柄和一块**客户区区域**，拿回原始像素
（BGRA、自上而下、不带 alpha 语义）。不做 OCR、不做定时调度、不编码落盘、不读业务
配置、不导入 PySide6。能力给全、业务按需。

面向「窗口宽高比固定、位置会变」的场景（典型是游戏窗口的任务区域）：

```python
from service.capture import CaptureRegion, NormalizedRegion, WindowCapturer

with WindowCapturer() as capturer:
    frame = capturer.capture(hwnd, NormalizedRegion(0.60, 0.14, 0.28, 0.29))

frame.width / frame.height    # 像素尺寸
frame.data                    # bytes，可直接喂 QImage.Format_ARGB32
frame.space                   # "client" 或 "screen"——本帧实际口径
frame.backend                 # "gdi-window" / "printwindow" / "screen" / "dxgi" / "wgc"
frame.degraded                # 是否由降级产生
```

### 后端矩阵

| 后端 | 实现 | 被遮挡时 | 独占全屏 | 说明 |
|---|---|---|---|---|
| `screen` | `GetDC(NULL)` + BitBlt | 截到遮挡者 | 拿到空白 | 屏幕物理像素，所见即所得 |
| `window` | `GetDC(hwnd)` + BitBlt | 仍拿窗口自身内容 | 可用 | 客户区像素，合成窗口常黑 |
| `printwindow` | `PrintWindow(PW_RENDERFULLCONTENT)` | 仍拿窗口自身内容 | 可用 | 窗口表面判黑后的第二次尝试 |
| `dxgi` | `IDXGIOutputDuplication` 桌面复制 | 截到遮挡者 | 拿到空白 | 屏幕物理像素，抗撕裂、可连续拉帧 |
| `wgc` | `windows-capture`（WinRT Graphics Capture） | **仍拿窗口自身内容** | 可用 | 客户端像素，唯一抗遮挡的一档，需 Win10 1903+ |

`backend="auto"`（默认）：先窗口表面 → 判黑（暗像素或近黑单色占比 ≥ 99.5%）→ 试
`PrintWindow` → 仍黑则试 `dxgi`（环境不支持就跳过）→ 最后退 `screen` 并标
`degraded=True`。`detect_blank=False` 时不做判黑。`wgc` **不参与** `auto`——它会启动
一条常驻捕获线程，只在业务明确要求「必须抗遮挡」时才显式指定。

### 关键契约

- **`space` 必须分清**：`client` 是窗口表面像素，`screen` 是屏幕物理像素。DPI-unaware
  程序被系统位图拉伸，同一区域在两种口径下尺寸不同（`WindowInfo` 同时给
  `client_width/height` 与 `screen_width/height`），混用必错位；
- **遮挡契约**：`screen` 与 `dxgi` 口径下被遮挡会截到**遮挡者的内容**——不是黑图，比黑图
  更难发现。默认抓取前做弱校验（区域中心 `WindowFromPoint` 的根祖先是否为目标窗口），
  命中即抛 `CaptureOccludedError`；`strict_foreground=True` 升级为「必须是前台窗口」；
- **越界**：默认钳制（`clamp_region=True`）；完全越界、或关掉钳制后任何越界，都抛
  `CaptureRegionError`；
- **区域两种写法**：`CaptureRegion(x, y, w, h)` 是像素，`NormalizedRegion(nx, ny, nw, nh)`
  是比例。后者运行时按当前尺寸换算，1280×720 ↔ 1920×1080 切换不必改配置；
- **异常**：`WindowNotFoundError` / `WindowNotVisibleError`（不可见或最小化）/
  `WindowOutOfScreenError` / `CaptureRegionError` / `CaptureOccludedError` /
  `CaptureUnavailableError` / `CaptureBackendError`；
- **硬前提**：独占全屏（FSE）绕过 DWM，`screen` 与 `dxgi` 拿到的是空白。游戏需用无边框
  窗口或窗口化才能稳定截取，这一点没有软件解法。

### DXGI 后端的额外约束

`backend="dxgi"` 是最快的一条路（区域 250×200 实测 1.06ms/帧），代价是几条硬限制：

- **只覆盖单个显示器**：区域跨屏直接抛 `CaptureUnavailableError`，不做拼接；
- **显示器旋转（90°/270°）不支持**：复制出的坐标与屏幕坐标不一致，抛
  `CaptureUnavailableError`；
- **首帧已丢弃**：复制接口刚建立时第一帧常是共享纹理的空帧（全黑），后端在打开后
  拉一次并丢弃，业务侧不必自己处理；
- **无新帧时复用缓存**：桌面静止时 `AcquireNextFrame` 会超时，同一区域沿用上一次结果；
  换了区域又长时间没有新帧才抛 `CaptureBackendError`；
- **容量限制**：一个进程在同一输出上只能有一个复制接口，整个会话最多 4 个进程并发；
  多个截图实例共存时要考虑这一点。

### WGC 后端的额外约束

`backend="wgc"` 是唯一「窗口被别的窗口盖住也照样拿到自己内容」的一档，代价是更慢
（区域 250×200 实测 6ms/次，含等待新帧）且有几条平台限制：

- **依赖第三方包**：`windows-capture`（Rust 扩展，229KB，复用已装的 numpy/opencv，
  不额外拉体积），已在 `pyproject.toml` 登记；缺包时请求该后端抛
  `CaptureUnavailableError`；
- **Win10 1903+**：本机 19045 实测可用。Win10 不支持 `IsBorderRequired` 与
  `minimum_update_interval` 两个设置项（传进去会让会话直接抛异常），所以都不传——
  Win10 没有捕获边框，Win11 会在被抓窗口外画一圈黄框，这是该 API 的既定行为；
- **常驻一条捕获线程**：会话在第一次 `open()` 时启动、`close()` 时停止；同一实例换
  窗口会重建会话，同一窗口重复 `open()` 只刷新尺寸快照；
- **帧是整窗口径**：尺寸等于窗口帧（含标题栏与边框），客户区在帧内的偏移由
  `client_origin - frame_rect` 算出，抓取时按该偏移裁剪，所以输出仍是 `client` 口径；
- **画面静止不产帧**：抓取先等 50ms 新帧，超时用缓存帧；
- **最小化不可用**：门面层的 `WindowNotVisibleError` 已拦在前面。



### 选区组件（gui/components/region_picker.py）

只产出坐标，不截图。覆盖所有显示器并集，悬停窗口虚线高亮、拖拽选框实时显示物理
尺寸、距客户区边缘 8px 吸附、拖拽不足 4px 视为单击选整窗、`Esc` 取消：

```python
from gui.components import RegionPicker

picker = RegionPicker()
picker.picked.connect(lambda r: print(r.hwnd, r.client_region, r.normalized_region))
picker.start()
```

`PickResult` 同时给屏幕物理矩形、客户区像素区域与归一化区域，业务侧按需取用。多显示器
混合缩放时物理坐标按「逻辑原点 × 比例」近似，单屏或统一缩放无偏差。


## 桌面入口

### GUI（PySide6 桌面界面）

设置页承载**程序级偏好**（`app` 配置段），切换立即生效并写回 `config.yaml`：

- 界面语言：`zh_CN` / `en`（Qt 标准 i18n，翻译源文件 `assets/i18n/zh_CN.ts`，当前只维护 `zh_CN`）。
  除本程序文案外，还会加载 PySide6 自带的 `qtbase_zh_CN.qm`，让 `QColorDialog`、
  `QFileDialog` 这类 Qt 合成控件的内建文案（确定/取消、色相/饱和度等）一起跟随界面语言；
- 界面主题：浅色 / 深色；
- 状态栏刷新间隔：`0.5 s` / `1 s` / `2 s` / `5 s`；
- 状态栏压力着色：任意数量渐变锚点（左键点轨道加锚点、右键锚点改色或删除）。

界面结构：主窗口中央是**背景层**（底色渐变 + 两处低饱和光斑），其上为
**自绘标题栏 + 页面堆叠区**，页面内容以**磨砂玻璃卡片**分组；都由设计令牌驱动，
主题只换令牌取值，页面无需改动代码。当前有两个页面：设置页（程序级偏好）与
示例页（`SamplePage`，仅用于验证导航条交互，后续可直接替换为业务页）。

设置页放两张卡片（外观 / 状态栏），卡片内是「分区标签 + 偏好行」，
**不再重复页面标题与说明文字**（当前页面已由导航胶囊标出，说明性文案属于冗余）。
偏好行用 `FieldRow`（标签与控件两列固定宽度，切语言不位移）；渐变条需要横向铺满，
改由 `WideFieldRow` 把控件放到标签的下一行。

标题栏（`gui/components/title_bar.py`）取代系统标题栏：左侧程序图标与「Sheep Box」，
中间嵌入导航条（含翻页箭头），右侧 36×30 的**最小化 / 最大化-还原 / 关闭**三键，
关闭键悬停变红；底部一条 1px 分隔线。它不自己实现拖动——拖动、双击最大化、贴边分屏、
四角缩放仍由系统完成，实现见 `gui/view/window_chrome.py`：

- Qt 侧声明 `FramelessWindowHint`（Qt 因此认为客户区 = 整个窗口，最大化按工作区计算，
  `mapToGlobal` 也不会被标题栏高度带偏）；
- 窗口样式补回 `WS_THICKFRAME | WS_SYSMENU | ...`（DWM 阴影、贴边、系统菜单不受影响）；
- `WM_NCCALCSIZE` 让客户区等于整个窗口（系统标题栏消失）；
- `WM_NCHITTEST` 分配命中区：标题栏空白/图标/标题 → `HTCAPTION`，导航项与三键 →
  `HTCLIENT`（不抢点击），四边按 DPI 换算的边框厚度 → 八个缩放方向；
- `WM_ENTERSIZEMOVE` / `WM_EXITSIZEMOVE` 期间冻结毛玻璃重算，拖动不掉帧；
- `DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)` 给 Win11 窗口圆角。

自绘标题栏只在 **Windows 真实窗口**下启用；设置 `SHEEPBOX_NATIVE_TITLEBAR=0` 可退回
「系统标题栏 + 玻璃导航条」的旧布局，用于排查平台问题。

导航条（`gui/components/nav_bar.py`）**占满整行**并左对齐：切页时左端点固定，只有胶囊的
右边界推出、旧胶囊的右边界压入，整条不会左右移动。嵌进标题栏后改用 `set_bare(True)` 去掉
玻璃底条（标题栏已有底色与分隔线，再叠一层会成"条中条"），底条样式仍保留给非标题栏布局：
小圆角与更弱的一档填充/高光，像贴着顶部的工具带而不是悬浮药丸。当前页展开为「图标 + 文字」
胶囊，其余页收缩为 32px 圆形图标，悬停用 tooltip 补全标题，宽度切换带 220ms 缓动。

项总宽超出可用宽度时自动进入**翻页模式**：两侧出现箭头（到边界时置灰），点击一次跨 **3 个
项**（并限制不超过一屏，项很宽时不会跳过头），滚轮为像素级细滚，两者都会对齐到项边界并让目标
项完整入镜；内容区左右边缘做 14px 渐隐，滚动中不会露出半个图标。

底部**状态栏**（`gui/components/status_bar.py`）右侧固定排列 CPU / GPU / 内存三项利用率与
压力色点：数字列定宽右对齐（容纳 `100%`），GPU 项按适配器数量动态增减（单卡显示 `GPU`、
多卡 `GPU 1/2…`，无 GPU 时整项隐藏），左侧用 `addStretch(1)` 把指标压在右侧。
采样由主窗口的 `QTimer` 驱动：`showEvent` 时惰性创建 `SystemCollector` 并按配置周期采样，
`closeEvent` 停止定时器并释放 PDH 句柄；采集失败只记一次日志、保留上一次显示。

颜色不是三段阈值，而是**同源渐变**（`gui/components/usage_gradient.py`）：锚点数量任意，
利用率按 **5% 粒度**量化后查缓存（最多 21 档），避免每次重画都做插值，配置变更时由主窗口
用 `set_gradient_stops()` 重建。

锚点编辑器 `GradientStopsControl` 把轨道画成渐变，轨道（6px）刻意比节点（12px）细：
**左键**点轨道空白处新增锚点（默认色取该位置的渐变采样值）、**左键按住节点拖动**改位置
（活动范围被左右邻居夹住，松手才广播一次变更，不会拖动中狂写配置）、**右键**锚点弹出浮层
（8 个预设色 + 自定义取色 + 删除）。每个节点旁跟随一个百分比标签，默认在节点上方，
相邻标签挤到一起时自动上下错开，控件高度按上下两排标签预留。

**0% 与 100% 两个端点固定**：画成**菱形**以区别于可拖动的圆形节点，不可拖动、不可删除，
只可改颜色；配置里缺端点时按最近锚点的颜色自动补齐，保证渐变始终覆盖 0~100。
中间锚点至少保留 2 个（凑不够两端就没有渐变），删除在端点与下限处都会被拒绝。

- `gui/theme/tokens.py`：颜色 / 8pt 间距 / 字号 / 圆角 / 控件尺寸 / 玻璃透明度与模糊半径，深浅两套；
- `gui/theme/style.py`：由令牌生成 QSS；`build_popup_stylesheet()` 专门生成下拉弹层样式；
- `gui/theme/background.py`：背景层，`backdrop_for()` 供卡片取自身区域的背景像素；
  调用 `set_image(path)` 可整体换成图片背景（自动虚化并叠色调遮罩，保证前景文本可读）；
- `gui/theme/blur.py`：高斯模糊工具（Qt 无 CSS `backdrop-filter`，用离屏 `QGraphicsBlurEffect` 实现）；
- `gui/components/`：`GlassCard`（半透明填充 + 背景模糊 + 1px 高光边 + 投影）、
  `FieldRow`（标签左 / 控件右，两列各自固定宽度，切换语言不位移）、`WideFieldRow`（标签独占
  一行、控件铺满下一行）、`SelectComboBox`（细线箭头）、`NavBar`（胶囊 / 圆形导航 + 溢出翻页，
  全自绘）、`TitleBar` / `WindowButton`（自绘标题栏与窗口三键）、`StatusBar`（底部指标栏）、
  `UsageGradient`（5% 粒度缓存取色）、`GradientStopsControl`（渐变锚点编辑器）。

下拉框分三态设计：关闭态近乎透明、只在悬停时显出边界（不切断玻璃卡片）；展开态边框
转强调色、箭头翻转；**弹层**为圆角卡片（10px）+ 4px 内衬 + 30px 选项高 + 悬停/选中底色，
与触发控件保持 6px 固定间距；下方放不下时自动翻到控件上方，两种情况都不遮住控件。

弹层实现有两处 Qt 约束：弹层宿主是独立顶层窗口 `QComboBoxPrivateContainer`，必须
`Frameless + WA_TranslucentBackground` 才能让圆角生效，且应用级 QSS 对它的命中不稳定，
样式要由控件直接下发到 `view` / `container`；QSS 的 `::item` 不支持 `min-height`，
选项高度只能由委托的 `sizeHint` 给出。

主题实现仍固定 `Fusion` 样式——Windows 原生 `windowsvista` 样式按系统主题绘制控件、
不读应用调色板，不固定样式时深色主题不生效。另需注意：应用 QSS 后 Qt 会用
`QStyleSheetStyle` 代理包装真实样式，`style().objectName()` 不再返回真实样式名。

OCR 等业务模块的运行参数不在 GUI 中编辑（`model.mode` / `thresholds` 等应由真正消费
OCR 的业务模块控制），当前通过 `config.yaml` 调整。

```bash
# 默认启动 GUI（普通用户入口）
python main.py
# 无头模式：不启动 GUI，仅初始化日志后退出
python main.py --no-gui
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
