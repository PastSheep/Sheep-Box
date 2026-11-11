# OCR 模块（service/ocr）

字节流 / base64（含 `data:...;base64,` 前缀）输入 → 结构化输出（`OCRResult`：items 含 text/bbox/score、elapsed、text 拼接）。
引擎基于 **RapidOCR（ONNX Runtime）**，已集成 PP-OCRv6 三档模型。
运行环境：Python **3.11+**（base 依赖 `onnxruntime==1.24.4`）。

> **职责边界**：本模块只负责识别与结构化输出，**不做文本清洗 / 后处理**（识别链路不
> 调用任何清洗函数）。需要去空白、去空行、去重、多栏合并等清洗的，由消费结构化输出的
> 业务模块自行实现——可复用下方的 `postprocess` 工具；`OCRResult.text` 保持原始拼接，
> 由消费方自行决定清洗口径。

## 后处理工具（供消费方复用，不在识别链路内）

`service.ocr.postprocess` 提供三个纯函数，`OCRManager` 不调用：

- `sort_into_lines(items)`：按框顶 + 框底共同判行（同排不同高也能归对），行内按中心 x
  升序、行间按行顶升序，返回行列表；
- `clean_whitespace(text)`：空格 / 换行 / 制表 / 全角空格归一为单空格；
- `normalize_chars(text)`：全角字母数字 → 半角，中文全角标点保留。

## 模型资源

- 规格：`tiny` / `small` / `medium`（PP-OCRv6，PPLCNetV4 骨干）。`ocr.model.mode` 决定启动
  加载方式（默认 `small`）：非 `all` 只加载 `mode` 对应的单档实例；`all` 三档全载，生效
  规格取 `ocr.model.default_spec`（默认 `small`）。
- 来源：魔搭 RapidAI/RapidOCR 仓库（`v3.10.0` tag），**不入库**（`.gitignore` 忽略 `assets/ocr/models/**/*.onnx` 与 `dict.txt`），部署时下载放置。
- 结构：`assets/ocr/models/{tiny,small,medium}/{det,rec,cls}.onnx` + `dict.txt`。
- 字典：tiny=`ppocrv6_tiny_dict.txt`，small/medium=`ppocrv6_dict.txt`（本地统一存为 `dict.txt`）。
- 方向分类（cls）三档共用 PP-OCRv5 的 `ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx`。

下载 URL 基底：
`https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/`

## 设备后端

- 无用户开关：GPU 自动探测与 CPU 回退全部在程序内部（`service/ocr/device.py`）。
- **CPU 包与 GPU 包互斥**：`onnxruntime`（base，CPU）与 `onnxruntime-directml` / `onnxruntime-gpu` 提供同名顶层模块，不能并存；dml / cuda **二选一，禁止同时安装**。
- 注意 pip extras 是**并集**：安装 `.[ocr-gpu-dml]` / `.[ocr-gpu-cuda]` 会同时装上 base 的 CPU 包，安装后需 `pip uninstall -y onnxruntime`（或使用干净环境只装 GPU 包）。
- GPU 首版仅 Windows，优先 DirectML（`onnxruntime-directml` 单包内含 CPU+GPU 两个 ExecutionProvider，**不会导致 CPU 不可用**；CPU 统一走 `CPUExecutionProvider`，品牌无关）。
- CUDA 后端（`onnxruntime-gpu`）为可选 extra（Linux / NVIDIA）。

## 开发注意（易踩坑）

- **rapidocr v3 API**：用 `RapidOCR(params={...})`，键形如 `"Det.engine_type"` / `"Cls.ocr_version"`，值用 Enum（`EngineType` / `ModelType` / `OCRVersion` 等）。
- **v6 配 v5 cls 模型时，必须传 `"Cls.ocr_version": OCRVersion.PPOCRV5`**——cls 输入 shape 由 `ocr_version` 决定（v4→[3,48,192]，v5→[3,80,160]），只传 `Cls.cls_image_shape` 不生效。
- 返回对象 `RapidOCROutput`（`.txts` / `.boxes` / `.scores` / `.elapse`，`.elapse` 即总耗时秒）。
- 配置中 `models.<spec>.dict_path` 为**必填**；模型相对路径基于配置文件所在目录解析。
- 非 `all` 模式只加载一个规格实例（由 `mode` 决定）；`set_model_spec` 先建新引擎再替换，
  切换成功后释放旧实例，重建失败则保留旧状态。
