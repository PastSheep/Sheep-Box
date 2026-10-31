"""OCR 后处理模块测试：判行排序、空白清洗、字符归一化。"""

from service.ocr.models import OCRTextItem
from service.ocr.postprocess import clean_whitespace, normalize_chars, sort_into_lines


def _item(text: str, bbox: list[list[int | float]]) -> OCRTextItem:
    return OCRTextItem(text=text, bbox=bbox, score=0.99)


# 实测 1000034997.jpg 的 4 个框（RapidOCR 输出）：
# 行1 = 判断题标签 + 正文第一行（cy 同为 73）；行2 = 正文第二行被拆成两框。
M_0 = _item(
    "2、铁路职工发现设备故障危及行车", [[205, 33], [1190, 33], [1190, 113], [205, 113]]
)
M_1 = _item("判断题", [[68, 51], [182, 51], [182, 95], [68, 95]])
M_2 = _item("和人身安全时，", [[46, 131], [509, 131], [509, 213], [46, 213]])
M_3 = _item("置之不理。", [[472, 135], [778, 135], [778, 209], [472, 209]])


def test_sort_into_lines_measured_bbox():
    """实测 bbox 数据：判为 2 行，行内按中心 x 排序，行间按行顶升序。"""
    lines = sort_into_lines([M_0, M_1, M_2, M_3])
    assert len(lines) == 2
    row1, row2 = lines
    # 行1：判断题(cx=125) 应排在正文第一行(cx=697) 之前 → 还原到行首
    assert [i.text for i in row1] == ["判断题", "2、铁路职工发现设备故障危及行车"]
    assert [i.text for i in row2] == ["和人身安全时，", "置之不理。"]


def test_sort_into_lines_different_heights_same_line():
    """同一排不同高：垂直区间重叠 → 判为同一行（仅中心 y 会误拆）。"""
    hi = _item("A", [[0, 0], [200, 0], [200, 200], [0, 200]])  # top0 bottom200 cy100
    lo = _item(
        "B", [[90, 90], [134, 90], [134, 134], [90, 134]]
    )  # top90 bottom134 cy112
    lines = sort_into_lines([hi, lo])
    assert len(lines) == 1
    # 行内按中心 x：hi(cx=100) 在 lo(cx=112) 前
    assert [i.text for i in lines[0]] == ["A", "B"]


def test_sort_into_lines_no_overlap_new_line():
    """垂直区间无交集 → 不同行；输入乱序也能按行顶排序。"""
    top = _item("顶", [[0, 0], [100, 0], [100, 40], [0, 40]])  # [0,40]
    bottom = _item("底", [[0, 60], [100, 60], [100, 100], [0, 100]])  # [60,100]
    lines = sort_into_lines([bottom, top])
    assert len(lines) == 2
    assert [i.text for i in lines[0]] == ["顶"]
    assert [i.text for i in lines[1]] == ["底"]


def test_sort_into_lines_empty():
    assert sort_into_lines([]) == []


def test_clean_whitespace_collapses_newlines_tabs():
    assert clean_whitespace("a\nb") == "a b"
    assert clean_whitespace("a\tb") == "a b"
    assert clean_whitespace("  a   b  ") == "a b"
    assert clean_whitespace("a\n\n\nb") == "a b"


def test_clean_whitespace_unicode_spaces():
    assert clean_whitespace("\u3000a\u3000b\u3000") == "a b"  # 全角空格
    assert clean_whitespace("a\u00a0b") == "a b"  # 不间断空格


def test_clean_whitespace_empty_and_plain():
    assert clean_whitespace("") == ""
    assert clean_whitespace("中文 文本") == "中文 文本"


def test_normalize_chars_fullwidth_to_halfwidth():
    assert normalize_chars("ＡＢＣ１２３") == "ABC123"
    assert normalize_chars("ａｂｃ") == "abc"
    assert normalize_chars("中文Ａ测试") == "中文A测试"


def test_normalize_chars_keeps_cjk_punct():
    assert normalize_chars("，。、；：？！") == "，。、；：？！"
    assert normalize_chars("“你好”") == "“你好”"


def test_normalize_chars_ideographic_space():
    assert normalize_chars("a\u3000b") == "a b"


def test_normalize_chars_chain_with_clean():
    assert clean_whitespace(normalize_chars("ＡＢＣ　１２３，")) == "ABC 123，"
