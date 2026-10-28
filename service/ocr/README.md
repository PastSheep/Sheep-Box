# OCR 模块（service/ocr）

字节流输入 → 结构化输出（`OCRResult`：items 含 text/bbox/score、elapsed、text 拼接、clean_text）。
引擎基于 **RapidOCR（ONNX Runtime）**，已集成 PP-OCRv6 三档模型。

## 模型资源

- 规格：`tiny` / `small` / `medium`（PP-OCRv6，PPLCNetV4 骨干），默认 `small`。
- 来源：魔搭 RapidAI/RapidOCR 仓库（`v3.10.0` tag），**不入库**（`.gitignore` 忽略 `assets/ocr/models/**/*.onnx` 与 `dict.txt`），部署时下载放置。
- 结构：`assets/ocr/models/{tiny,small,medium}/{det,rec,cls}.onnx` + `dict.txt`。
- 字典：tiny=`ppocrv6_tiny_dict.txt`，small/medium=`ppocrv6_dict.txt`（本地统一存为 `dict.txt`）。
- 方向分类（cls）三档共用 PP-OCRv5 的 `ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx`。

下载 URL 基底：
`https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/`

## 设备后端

- 仅暴露 `gpu_enabled` 布尔开关；自动探测与 CPU 回退全部在程序内部（`service/ocr/device.py`）。
- GPU 首版仅 Windows，默认启用 DirectML（`onnxruntime-directml` 单包内含 CPU+GPU 两个 ExecutionProvider，**不会导致 CPU 不可用**；CPU 统一走 `CPUExecutionProvider`，品牌无关）。
- CUDA 后端（`onnxruntime-gpu`）为可选 extra（Linux / NVIDIA）。
- 多后端**不需要也不应双装**：GPU 包与 `onnxruntime` 顶层模块同名无法同时安装，共存靠单包多 EP。

## 开发注意（易踩坑）

- **rapidocr v3 API**：用 `RapidOCR(params={...})`，键形如 `"Det.engine_type"` / `"Cls.ocr_version"`，值用 Enum（`EngineType` / `ModelType` / `OCRVersion` 等）。
- **v6 配 v5 cls 模型时，必须传 `"Cls.ocr_version": OCRVersion.PPOCRV5`**——cls 输入 shape 由 `ocr_version` 决定（v4→[3,48,192]，v5→[3,80,160]），只传 `Cls.cls_image_shape` 不生效。
- 返回对象 `RapidOCROutput`（`.txts` / `.boxes` / `.scores` / `.elapse`，`.elapse` 即总耗时秒）。
- 配置中 `models.<spec>.dict_path` 为**必填**；模型相对路径基于配置文件所在目录解析。
- 非 `all` 模式只同时加载一个规格实例，`set_model_spec` 切换时释放旧实例。
