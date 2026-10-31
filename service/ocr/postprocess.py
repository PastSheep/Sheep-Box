"""OCR 结构化输出的后处理工具（供消费方复用）。

职责边界：本模块面向**未来消费 OCR 结构化结果的功能模块**提供文本 / 版面
后处理能力，**不参与识别链路**——:class:`OCRManager` 不调用本模块，OCR
模块依旧只负责"识别 + 结构化输出"（清洗 / 后处理由消费方按需调用）。

提供的工具（纯函数，无副作用）：
- :func:`sort_into_lines`：按版面几何判行并对行内文本排序（还原阅读顺序）；
- :func:`clean_whitespace`：归一化空格 / 换行 / 制表等空白；
- :func:`normalize_chars`：统一中英文字符（全角字母数字 → 半角）。

输入基于 :class:`OCRTextItem` 的 ``bbox``（四边形 4 顶点），不依赖引擎实现。
"""

from service.ocr.models import OCRTextItem

__all__ = ["clean_whitespace", "normalize_chars", "sort_into_lines"]


def _bbox_extents(
    bbox: list[list[int | float]],
) -> tuple[float, float, float, float]:
    """从四边形 bbox 提取版面几何：top / bottom / 中心 x / 中心 y。

    Args:
        bbox: 四边形 4 个顶点，形如 ``[[x1, y1], [x2, y2], ...]``。

    Returns:
        ``(top, bottom, center_x, center_y)``，坐标取均值。
    """
    xs = [float(p[0]) for p in bbox]
    ys = [float(p[1]) for p in bbox]
    return min(ys), max(ys), sum(xs) / len(xs), sum(ys) / len(ys)


def _vertical_overlap(
    top_a: float, bottom_a: float, top_b: float, bottom_b: float
) -> bool:
    """两框垂直区间是否有交集（``max(top) < min(bottom)``）。

    用「框顶 + 框底共同判定」而非仅中心 y：同一排不同高的框（垂直区间
    仍相交）也能正确判为同一行。

    Args:
        top_a / bottom_a: 框 A 的垂直区间。
        top_b / bottom_b: 框 B 的垂直区间。

    Returns:
        区间有交集返回 ``True``。
    """
    return max(top_a, top_b) < min(bottom_a, bottom_b)


def sort_into_lines(items: list[OCRTextItem]) -> list[list[OCRTextItem]]:
    """按版面几何把文本项归为「行」并还原阅读顺序。

    判行依据**框顶与框底共同判定**：两框垂直区间有交集（含同排不同高）
    视为同一行；行内按中心 x 升序，行间按行顶升序。

    Args:
        items: OCR 识别的文本项列表（含 ``bbox``）。

    Returns:
        行列表：每行是一个按阅读顺序排列的文本项列表。
    """
    if not items:
        return []

    # (item, top, bottom, center_x)
    entries: list[tuple[OCRTextItem, float, float, float]] = []
    for item in items:
        top, bottom, cx, _cy = _bbox_extents(item.bbox)
        entries.append((item, top, bottom, cx))

    entries.sort(key=lambda e: e[1])  # 按 top 升序，保证行按从上到下构建

    lines: list[list[tuple[OCRTextItem, float, float, float]]] = []
    for entry in entries:
        _item, top, bottom, _cx = entry
        placed = False
        for line in lines:
            # 与行内任一框垂直区间有交集 → 同一行
            if any(_vertical_overlap(top, bottom, e[1], e[2]) for e in line):
                line.append(entry)
                placed = True
                break
        if not placed:
            lines.append([entry])

    # 行内按中心 x 升序；行间按行顶升序
    for line in lines:
        line.sort(key=lambda e: e[3])
    lines.sort(key=lambda line: min(e[1] for e in line))

    return [[e[0] for e in line] for line in lines]


def clean_whitespace(text: str) -> str:
    """归一化空格 / 换行 / 制表等空白，压缩连续空白为单空格。

    基于 ``str.split()`` 按 Unicode 空白切分后以单空格拼接，因此
    ``\\n`` / ``\\r`` / ``\\t`` / 全角空格（U+3000）/ 不间断空格（U+00A0）
    等一律归一为普通空格，并去除首尾空白。

    Args:
        text: 待清洗文本。

    Returns:
        清洗后的文本（连续空白合并为单空格）。
    """
    return " ".join(text.split())


def normalize_chars(text: str) -> str:
    """统一中英文字符形态：全角字母 / 数字 → 半角，全角空格 → 半角空格。

    仅归一化**可安全转换**的字符：全角英文字母（Ａ-Ｚ、ａ-ｚ）、全角数字
    （０-９）及全角空格（U+3000）。中文全角标点（，。、；：？！等）**保留**
    全角形态，避免破坏中文排版。

    Args:
        text: 待归一化文本。

    Returns:
        归一化后的文本（英数字统一为半角，中文标点保持）。
    """
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if (
            0xFF10 <= code <= 0xFF19
            or 0xFF21 <= code <= 0xFF3A
            or 0xFF41 <= code <= 0xFF5A
        ):  # ０-９ → 0-9
            out.append(chr(code - 0xFEE0))
        elif ch == "\u3000":  # 全角空格 → 半角空格
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)
