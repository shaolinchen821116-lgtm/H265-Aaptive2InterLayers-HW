#!/usr/bin/env python3
"""Generate the P-frame CU32-only training and ABCE validation Word report."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "docs" / "P帧高一层保守门控_训练与ABCE验证报告_zh.docx"
FLOW = ROOT / "docs" / "assets" / "p_inter_only32_flow.png"
RESULTS = ROOT / "results" / "inter" / "only32_abce_30f"
TRAIN = ROOT / "results" / "inter" / "only32_classb_train"
ACE = ROOT / "results" / "inter" / "only32_ace_independent"

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
INK = "0B2545"
MUTED = "667085"
GRID = "AAB7C4"
HEADER_FILL = "E8EEF5"
LIGHT = "F4F6F9"
GOOD = "EAF4EA"
CAUTION = "FFF4D6"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def set_font(run, size=None, bold=None, color=None, italic=None,
             ascii_font="Calibri", east_asia="Microsoft YaHei"):
    run.font.name = ascii_font
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), ascii_font)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), ascii_font)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.insert_element_before(
            shd, "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText",
            "w:vAlign", "w:hideMark", "w:headers", "w:cellIns",
            "w:cellDel", "w:cellMerge", "w:tcPrChange")
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width))
    tc_w.set(qn("w:type"), "dxa")


def set_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.insert_element_before(
            borders, "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
            "w:tblCaption", "w:tblDescription", "w:tblPrChange")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), "4")
        tag.set(qn("w:color"), GRID)


def fixed_table(doc, headers, rows, widths, font_size=8.7, aligns=None,
                cell_margin_tb=80):
    assert sum(widths) == 9360
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), "9360")
    tbl_w.set(qn("w:type"), "dxa")
    for duplicate in list(tbl_pr.findall(qn("w:tblInd"))):
        tbl_pr.remove(duplicate)
    tbl_ind = OxmlElement("w:tblInd")
    tbl_ind.set(qn("w:w"), "120")
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_pr.insert_element_before(
        tbl_ind, "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar",
        "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange")
    for duplicate in list(tbl_pr.findall(qn("w:tblLayout"))):
        tbl_pr.remove(duplicate)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.insert_element_before(
        layout, "w:tblCellMar", "w:tblLook", "w:tblCaption",
        "w:tblDescription", "w:tblPrChange")
    grid_cols = table._tbl.tblGrid.findall(qn("w:gridCol"))
    for node, width in zip(grid_cols, widths):
        node.set(qn("w:w"), str(width))
    set_table_borders(table)
    header = table.rows[0]
    tr_pr = header._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)
    for index, (cell, text) in enumerate(zip(header.cells, headers)):
        set_cell_width(cell, widths[index])
        set_cell_margins(cell, top=cell_margin_tb, bottom=cell_margin_tb)
        shade(cell, HEADER_FILL)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p.add_run(str(text)), size=font_size, bold=True, color=INK)
    for row_data in rows:
        row = table.add_row()
        cant = OxmlElement("w:cantSplit")
        row._tr.get_or_add_trPr().append(cant)
        for index, (cell, value) in enumerate(zip(row.cells, row_data)):
            set_cell_width(cell, widths[index])
            set_cell_margins(cell, top=cell_margin_tb, bottom=cell_margin_tb)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            if aligns:
                p.alignment = aligns[index]
            set_font(p.add_run(str(value)), size=font_size, color="202124")
    doc.add_paragraph(style="Table Citation")
    return table


def set_repeat_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(paragraph.add_run("第 "), size=9, color=MUTED)
    field_run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    field_run._r.extend([begin, instr, separate, end])
    set_font(paragraph.add_run(" 页"), size=9, color=MUTED)


def add_numbering(doc):
    numbering = doc.part.numbering_part.element
    existing_abs = [int(node.get(qn("w:abstractNumId"))) for node in numbering.findall(qn("w:abstractNum"))]
    existing_num = [int(node.get(qn("w:numId"))) for node in numbering.findall(qn("w:num"))]
    abstract_id = max(existing_abs or [0]) + 1
    num_id = max(existing_num or [0]) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "decimal")
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "%1.")
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    p_pr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "540")
    tabs.append(tab)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "540")
    ind.set(qn("w:hanging"), "270")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:after"), "80")
    spacing.set(qn("w:line"), "300")
    spacing.set(qn("w:lineRule"), "auto")
    p_pr.extend([tabs, ind, spacing])
    lvl.extend([start, num_fmt, lvl_text, lvl_jc, p_pr])
    abstract.append(lvl)
    first_num = numbering.find(qn("w:num"))
    if first_num is None:
        numbering.append(abstract)
    else:
        numbering.insert(numbering.index(first_num), abstract)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abs_ref = OxmlElement("w:abstractNumId")
    abs_ref.set(qn("w:val"), str(abstract_id))
    num.append(abs_ref)
    numbering.append(num)
    return num_id


def add_numbered(doc, num_id, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    p_pr = p._p.get_or_add_pPr()
    num_pr = p_pr.get_or_add_numPr()
    num_pr.get_or_add_ilvl().set(qn("w:val"), "0")
    num_pr.get_or_add_numId().set(qn("w:val"), str(num_id))
    set_font(p.add_run(text), size=11)
    return p


def add_para(doc, text="", bold_prefix=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.25
    if bold_prefix and text.startswith(bold_prefix):
        set_font(p.add_run(bold_prefix), size=11, bold=True, color=INK)
        set_font(p.add_run(text[len(bold_prefix):]), size=11)
    else:
        set_font(p.add_run(text), size=11)
    return p


def add_code(doc, lines):
    for line in lines:
        p = doc.add_paragraph(style="Code Block")
        p.paragraph_format.keep_together = True
        set_font(p.add_run(line), size=8.5, ascii_font="Consolas", east_asia="Microsoft YaHei")


def heading(doc, text, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    set_font(p.add_run(text), bold=True)
    return p


def render_flowchart(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1600, 1080), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 31)
    small = ImageFont.truetype(str(font_path), 27)
    bold = ImageFont.truetype(str(Path("C:/Windows/Fonts/msyhbd.ttc")), 31)

    def box(x, y, w, h, text, fill="#E8EEF5", outline="#2E74B5", use_bold=False):
        draw.rounded_rectangle((x, y, x+w, y+h), radius=18, fill=fill, outline=outline, width=4)
        fnt = bold if use_bold else font
        bbox = draw.multiline_textbbox((0, 0), text, font=fnt, spacing=8, align="center")
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw.multiline_text((x+(w-tw)/2, y+(h-th)/2), text, font=fnt,
                            fill="#0B2545", spacing=8, align="center")

    def arrow(x1, y1, x2, y2, label=None):
        draw.line((x1, y1, x2, y2), fill="#415A77", width=5)
        import math
        angle = math.atan2(y2-y1, x2-x1)
        for delta in (2.55, -2.55):
            draw.line((x2, y2, x2+20*math.cos(angle+delta), y2+20*math.sin(angle+delta)),
                      fill="#415A77", width=5)
        if label:
            draw.text(((x1+x2)/2+8, (y1+y2)/2-34), label, font=small, fill="#7A5A00")

    box(525, 25, 550, 95, "P 帧 CU32 根节点", use_bold=True)
    box(455, 175, 690, 115, "PME → IME 根探针\n保留 SAD、MV、AMVP、活动度")
    box(465, 345, 670, 105, "7 个整数特征 + 深度 6 CART")
    box(515, 505, 570, 105, "only32 概率 ≥ 92？", fill="#FFF4D6", outline="#B7791F", use_bold=True)
    box(70, 680, 440, 110, "是：只搜索 CU32", fill="#EAF4EA", outline="#3B7A57")
    box(590, 680, 440, 110, "否：原高/低两层树\ncutoff = 50")
    box(1090, 680, 440, 110, "低层概率 ≥ 50？", fill="#FFF4D6", outline="#B7791F")
    box(600, 895, 360, 105, "搜索 CU32 + CU16")
    box(1070, 895, 360, 105, "搜索 CU16 + CU8")
    arrow(800, 120, 800, 175)
    arrow(800, 290, 800, 345)
    arrow(800, 450, 800, 505)
    arrow(515, 557, 290, 680, "是")
    arrow(800, 610, 800, 680, "否")
    arrow(1030, 735, 1090, 735)
    arrow(1310, 790, 1250, 895, "是")
    arrow(1150, 790, 780, 895, "否")
    draw.text((90, 1015), "各分支保留本层 AMVP / Merge / RDO 比较；门控只限制 CU 递归层级。",
              font=small, fill="#4B5563")
    image.save(path, dpi=(180, 180))


def configure_styles(doc):
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(11)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25
    for level, size, color, before, after in (
        (1, 16, BLUE, 18, 10), (2, 13, BLUE, 14, 7), (3, 12, DARK_BLUE, 10, 5)):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
    styles = doc.styles
    if "Code Block" not in styles:
        code = styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
    else:
        code = styles["Code Block"]
    code.font.name = "Consolas"
    code._element.rPr.rFonts.set(qn("w:ascii"), "Consolas")
    code._element.rPr.rFonts.set(qn("w:hAnsi"), "Consolas")
    code._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    code.font.size = Pt(8.5)
    code.paragraph_format.left_indent = Inches(0.18)
    code.paragraph_format.right_indent = Inches(0.08)
    code.paragraph_format.space_before = Pt(0)
    code.paragraph_format.space_after = Pt(0)
    code.paragraph_format.line_spacing = 1.0
    if "Table Citation" not in styles:
        citation = styles.add_style("Table Citation", WD_STYLE_TYPE.PARAGRAPH)
    else:
        citation = styles["Table Citation"]
    citation.font.name = "Calibri"
    citation.font.size = Pt(8)
    citation.font.color.rgb = RGBColor.from_string(MUTED)
    citation.paragraph_format.space_before = Pt(4)
    citation.paragraph_format.space_after = Pt(4)


def add_title_page(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(4)
    set_font(p.add_run("技术研究报告"), size=11, bold=True, color=BLUE)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("P 帧“高一层”保守门控"), size=24, bold=True, color=INK)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(18)
    set_font(p.add_run("在高两层 / 低两层自适应基础上增加 CU32-only 选择"), size=14, color=DARK_BLUE)
    rows = [
        ("研究平台", "x265 硬件友好 PME → IME → FME 分支"),
        ("测试集合", "HEVC Class A/B/C/E，共 17 序列"),
        ("测试长度", "每点 30 帧：1 个 I 帧 + 29 个 P 帧"),
        ("码率点", "固定 QP 22 / 27 / 32 / 37"),
        ("最终配置", "mode 6；two-layer cutoff 50；only32 cutoff 92"),
        ("日期", "2026-08-21"),
    ]
    fixed_table(doc, ["项目", "内容"], rows, [2200, 7160], font_size=9.5,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("核心结论"), size=13, bold=True, color=BLUE)
    fixed_table(doc, ["增量 BDRate", "最差序列增量", "CU32-only 率", "独立触发精度"],
                [("+0.002%", "+0.080%", "6.425%", "93.390%")],
                [2340, 2340, 2340, 2340], font_size=10,
                aligns=[WD_ALIGN_PARAGRAPH.CENTER]*4)
    add_para(doc, "结论口径：增量 BDRate 以原高两层/低两层自适应为参考；相对完整三层的总损失为 +1.500%。")


def build_report():
    render_flowchart(FLOW)
    doc = Document()
    configure_styles(doc)
    intro_num_id = add_numbering(doc)
    section = doc.sections[0]
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_font(header.add_run("P 帧高一层保守门控 | x265 HW-HME"), size=9, color=MUTED)
    set_repeat_page_number(section.footer.paragraphs[0])
    add_title_page(doc)

    heading(doc, "1. 研究目标与结论边界", 1)
    add_para(doc, "目标是在既有高两层 32/16 与低两层 16/8 自适应选择之前，增加一个只保留 CU32 的高一层控制，并把高一层本身相对原两层方案的压缩率损失控制在 0.5% 内。")
    for item in (
        "推荐 cutoff 92：17 序列平均增量 +0.002%，最差增量 +0.080%。",
        "较激进 cutoff 89：平均增量 +0.042%，但 vidyo1 达到 +0.784%，不作为默认值。",
        "强制 CU32-only：平均 +35.860%，说明必须采用低误触发的保守门控。",
        "30 帧属于研究级短序列；迁移到新平台后仍须重采标签和复测长序列。",
    ):
        add_numbered(doc, intro_num_id, item)

    heading(doc, "2. 三级级联算法", 1)
    add_para(doc, "每个 P 帧 CU32 先完成根节点 PME/IME 探针。高一层 CART 只决定是否禁止向 CU16/CU8 递归；没有触发时，继续运行原高两层/低两层 CART。各允许层内部仍完成 AMVP、Merge 和 RDO 比较。")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    p.add_run().add_picture(str(FLOW), width=Inches(6.3))
    p = doc.add_paragraph(style="Table Citation")
    set_font(p.add_run("图 1  P 帧 CU32-only → 高两层/低两层的三级级联流程"), size=8, color=MUTED)
    doc.add_page_break()
    fixed_table(doc, ["Mode", "含义", "用途"], [
        ("0", "完整 32/16/8 三层", "BDRate anchor"),
        ("1", "强制高两层 32/16", "边界对照"),
        ("2", "强制低两层 16/8", "边界对照"),
        ("3", "原高/低两层自适应", "高一层增量 anchor"),
        ("4", "完整 RDO + INTERLAYERSTAT", "训练标签采集"),
        ("5", "强制 CU32-only", "高一层边界对照"),
        ("6", "CU32-only 门控，失败后回退 mode 3", "最终方案"),
    ], [900, 3900, 4560], font_size=9,
        aligns=[WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])

    heading(doc, "3. 特征与硬件复杂度", 1)
    features = [
        ("qp", "帧级固定 QP", "寄存器读取"),
        ("ime_sad_q8", "(IME_SAD + 2) >> 2；CU32 SAD/像素 Q8", "加法 + 右移"),
        ("refine_l1", "|IME MV − PME seed| 的 x/y L1", "绝对值 + 加法"),
        ("mvd_qpel_l1", "|IME MV×4 − AMVPqpel| 的 x/y L1", "左移 + 绝对值 + 加法"),
        ("mv_fullpel_l1", "|IME MVx| + |IME MVy|", "绝对值 + 加法"),
        ("pme_activity", "CU32 下采样 8×8 的均值梯度", "绝对差 + 累加"),
        ("ime_boundary", "IME 最优点是否在搜索窗边界", "比较"),
    ]
    fixed_table(doc, ["特征", "定义", "硬件运算"], features, [2300, 4700, 2360], font_size=8.7,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT]*3)
    add_para(doc, "最终 CART 最大深度 6，仅含整数比较和常数概率返回；不估算 bits，也不在门控中计算乘法或平方根。当前最终树的最高叶值为 94，因此 cutoff 92 与 94 在本模型上命中同一叶。")

    heading(doc, "4. 数据采集与标签格式", 1)
    add_para(doc, "训练集合为 Class B 五个序列，每序列 QP 22/27/32/37、每点 12 帧，共 448,800 个 CU32 样本。mode 4 不裁剪任何 CU 层，标签来自最终完整 32/16/8 RDO。")
    add_code(doc, [
        "python experiments/inter_hw_hme/run_classb.py ^",
        "  --encoder D:/path/to/x265.exe --manifest sequence_manifest_abce.csv ^",
        "  --output D:/work/classb_collect --modes hw --frames 12 ^",
        "  --qps 22,27,32,37 --layer-mode 4 --force",
    ])
    add_para(doc, "单样本日志：", bold_prefix="单样本日志：")
    add_code(doc, [
        "INTERLAYERSTAT,<ctu_addr>,<pel_x>,<pel_y>,<qp>,<ime_sad_q8>,",
        "<refine_l1>,<mvd_qpel_l1>,<mv_fullpel_l1>,<pme_activity>,",
        "<ime_boundary>,<leaf32>,<leaf16>,<leaf8>,<two_layer_oracle>",
    ])
    fixed_table(doc, ["字段", "训练含义"], [
        ("leaf32 > 0", "CU32-only 正样本；CTU32 根节点未递归"),
        ("leaf16 / leaf8", "完整 RDO 的 16×16 / 8×8 叶 CU 数"),
        ("two_layer_oracle", "原两层树使用；高一层树不使用该字符串"),
        ("runs.csv", "保存序列、QP、PSNR、码率、速度与日志对应关系"),
    ], [2500, 6860], font_size=9.2,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])

    heading(doc, "5. CART 训练、阈值扫描与导出", 1)
    train_num_id = add_numbering(doc)
    for item in (
        "解析 mode-4 日志，形成 7 维整数输入和 leaf32>0 标签。",
        "逐节点枚举整数阈值，以加权 Gini 最小选择分裂。",
        "最大深度 6；min leaf 512；正样本权重 1.0。",
        "按序列进行 leave-one-sequence-out，不把同一序列 CTU 随机拆散。",
        "扫描概率 cutoff，并用真实编码 BDRate 的最差序列约束确定 92。",
        "全量 Class B 重训，导出 JSON、文本、x265 C++ 和 ISO C99 模型。",
    ):
        add_numbered(doc, train_num_id, item)
    add_code(doc, [
        "python experiments/inter_hw_hme/train_inter_only32_gate.py D:/work/classb_collect/runs.csv ^",
        "  --output results/inter/only32_classb_train --max-depth 6 --min-leaf 512 ^",
        "  --positive-weight 1.0 --recommended-cutoff 92 ^",
        "  --portable-header experiments/inter_hw_hme/portable_c/inter_only32_gate_model.h",
    ])
    fixed_table(doc, ["输出", "内容"], [
        ("inter_only32_tree.json", "元数据、特征顺序、最终树、验证摘要"),
        ("inter_only32_tree.txt", "人工审查用 if/else 树"),
        ("inter_only32_thresholds_cv.csv", "cutoff 扫描的 precision / recall / false gate"),
        ("inter_only32_sequence_cv.csv", "Class B 留一序列结果"),
        ("inter_only32_gate_model.h / _c.h", "x265 C++ 集成头 / ISO C99 移植头"),
    ], [3500, 5860], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])

    heading(doc, "6. 分类验证：判断正确概率", 1)
    train_cv = read_csv(TRAIN / "inter_only32_sequence_cv.csv")[-1]
    ace_classes = read_csv(ACE / "inter_only32_independent_classes.csv")
    rows = [("Class B LOO", f'{int(float(train_cv["samples"])):,}',
             f'{float(train_cv["oracle_only32_pct"]):.3f}%',
             f'{float(train_cv["selected_only32_pct"]):.3f}%',
             f'{float(train_cv["precision_pct"]):.3f}%',
             f'{float(train_cv["false_gate_pct"]):.3f}%')]
    for row in ace_classes:
        if row["name"].startswith("All"):
            continue
        rows.append((row["name"], f'{int(float(row["samples"])):,}',
                     f'{float(row["oracle_only32_pct"]):.3f}%',
                     f'{float(row["selected_only32_pct"]):.3f}%',
                     f'{float(row["precision_pct"]):.3f}%',
                     f'{float(row["false_gate_pct"]):.3f}%'))
    ace_overall = json.loads((ACE / "inter_only32_independent_summary.json").read_text(encoding="utf-8"))["overall"]
    rows.append(("A/C/E 合计", f'{int(ace_overall["samples"]):,}',
                 f'{ace_overall["oracle_only32_pct"]:.3f}%',
                 f'{ace_overall["selected_only32_pct"]:.3f}%',
                 f'{ace_overall["precision_pct"]:.3f}%',
                 f'{ace_overall["false_gate_pct"]:.3f}%'))
    fixed_table(doc, ["集合", "样本", "RDO 标签率", "预测选中率", "触发精度", "误触发率"],
                rows, [1550, 1550, 1550, 1550, 1580, 1580], font_size=8.4,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])
    add_para(doc, "“判断正确概率”采用触发精度 TP/(TP+FP)。保守门控会故意产生大量 false-negative：它降低覆盖率，却不把错误层强制给编码器；因此总体 accuracy 不适合作为主指标。")

    heading(doc, "7. ABCE 30 帧 BDRate 结果", 1)
    full_rows = {row["sequence"]: row for row in read_csv(RESULTS / "cutoff92_vs_full3" / "bd_rate_summary.csv") if row["class"] != "All"}
    inc_rows = {row["sequence"]: row for row in read_csv(RESULTS / "cutoff92_vs_two_layer" / "bd_rate_summary.csv") if row["class"] != "All"}
    sequence_rows = []
    for sequence in sorted(full_rows, key=lambda name: (full_rows[name]["class"], name)):
        cls = full_rows[sequence]["class"].replace("Class", "")
        sequence_rows.append((cls, sequence,
                              f'{float(full_rows[sequence]["bd_rate_y_psnr_pct"]):+.3f}%',
                              f'{float(inc_rows[sequence]["bd_rate_y_psnr_pct"]):+.3f}%'))
    fixed_table(doc, ["Class", "序列", "对完整三层", "对原两层增量"], sequence_rows,
                [1100, 3800, 2230, 2230], font_size=8.0, cell_margin_tb=40,
                aligns=[WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])

    doc.add_page_break()
    class_full = read_csv(RESULTS / "cutoff92_vs_full3" / "class_bd_rate_summary.csv")
    class_inc = {row["class"]: row for row in read_csv(RESULTS / "cutoff92_vs_two_layer" / "class_bd_rate_summary.csv")}
    class_rows = []
    for row in class_full:
        if row["class"] == "All classes":
            continue
        other = class_inc[row["class"]]
        class_rows.append((row["class"],
                           f'{float(row["bd_rate_y_psnr_mean_pct"]):+.3f}%',
                           f'{float(other["bd_rate_y_psnr_mean_pct"]):+.3f}%',
                           f'{float(other["worst_sequence_bd_rate_pct"]):+.3f}%'))
    class_rows.append(("All", "+1.500%", "+0.002%", "+0.080%"))
    fixed_table(doc, ["类别", "对完整三层平均", "对原两层平均增量", "该类最差增量"], class_rows,
                [1800, 2520, 2520, 2520], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])

    heading(doc, "8. 实际选层率、阈值对照与风险", 1)
    runs = read_csv(RESULTS / "cutoff92_vs_full3" / "runs.csv")
    grouped = defaultdict(lambda: [0, 0, 0])
    for row in runs:
        values = grouped[row["class"]]
        values[0] += int(float(row["layer_only32"]))
        values[1] += int(float(row["layer_high2"]))
        values[2] += int(float(row["layer_low2"]))
    selection = []
    totals = [0, 0, 0]
    for cls in sorted(grouped):
        vals = grouped[cls]
        total = sum(vals)
        selection.append((cls, *(f"{100*v/total:.2f}%" for v in vals)))
        totals = [a+b for a, b in zip(totals, vals)]
    selection.append(("All", *(f"{100*v/sum(totals):.3f}%" for v in totals)))
    fixed_table(doc, ["类别", "CU32-only", "高两层 32/16", "低两层 16/8"], selection,
                [1800, 2520, 2520, 2520], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])
    fixed_table(doc, ["策略", "对完整三层", "对原两层增量", "CU32-only 率", "速度比"], [
        ("强制 CU32-only", "+35.860%", "—", "100%", "3.280×"),
        ("级联 cutoff 89", "+1.542%", "+0.042%", "15.707%", "1.385×"),
        ("级联 cutoff 92", "+1.500%", "+0.002%", "6.425%", "1.397×"),
    ], [2700, 1665, 1665, 1665, 1665], font_size=8.8,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT])
    add_para(doc, "强制高一层最差为 BQMall +77.450%。cutoff 89 的 vidyo1 增量为 +0.784%，超过逐序列 0.5% 目标；cutoff 92 的 17 序列最差仅 +0.080%，故选为默认。")

    heading(doc, "9. 运行与复现命令", 1)
    add_code(doc, [
        "--preset medium --tune zerolatency --qp <QP>",
        "--ctu 32 --min-cu-size 8 --no-rect --no-amp --max-tu-size 32",
        "--bframes 0 --ref 1 --frame-threads 1 --no-scenecut",
        "--hw-hme --hw-hme-pme-range 32,28 --hw-hme-ime-range 12,12",
        "--hw-hme-pme-cost-mode 1 --hw-hme-pme-rate-scale 256",
        "--hw-hme-pme-texture 8,24 --hw-hme-pme-attractor 1",
        "--hw-hme-inter-layers 6 --hw-hme-layer-cutoff 50",
        "--hw-hme-only32-cutoff 92 --hw-hme-stats",
    ])
    add_code(doc, [
        "python experiments/inter_hw_hme/run_inter_layer_sweep.py ^",
        "  --encoder D:/path/to/x265.exe --manifest sequence_manifest_abce.csv ^",
        "  --anchor-runs D:/work/full3/runs.csv --anchor-mode hw ^",
        "  --frames 30 --qps 22,27,32,37 ^",
        "  --variants 5:50:92,6:50:89,6:50:92 --force",
    ])

    heading(doc, "10. C99 移植步骤", 1)
    port_num_id = add_numbering(doc)
    for item in (
        "从 portable_c/hw_hme_reference.* 建立目标平台参考，并编译 test_hw_hme。",
        "由训练脚本生成 inter_only32_gate_model.h；不要手工抄写树。",
        "统一 PME 下采样像素、IME full-pel 和 AMVP qpel 三种坐标精度。",
        "只在 CTU32 根节点、正方形 CU=PU=TU 配置调用高一层门控。",
        "触发 CU32-only 后仍完成 CU32 AMVP、Merge、残差与 RDO；只禁止递归。",
        "未触发时必须回到高两层/低两层树，而不是改变为其他搜索集合。",
        "新平台用 mode 4 重采标签，按序列交叉验证，再检查逐序列增量 BDRate。",
    ):
        add_numbered(doc, port_num_id, item)
    add_code(doc, [
        "cmake -S experiments/inter_hw_hme/portable_c -B build/portable-c",
        "cmake --build build/portable-c",
        "ctest --test-dir build/portable-c --output-on-failure",
    ])

    doc.add_page_break()
    heading(doc, "11. 文件索引与结论", 1)
    fixed_table(doc, ["路径", "说明"], [
        ("x265_overlay/source/encoder/inter_layer_selector.h", "x265 三级决策接口"),
        ("x265_overlay/source/encoder/inter_only32_gate_model.h", "集成的 C++ 整数树"),
        ("experiments/inter_hw_hme/train_inter_only32_gate.py", "训练与 C/C++ 导出"),
        ("experiments/inter_hw_hme/evaluate_inter_only32_gate.py", "固定模型独立验证"),
        ("experiments/inter_hw_hme/portable_c/", "独立 C99 搜索与选层接口"),
        ("results/inter/only32_classb_train/", "训练树与交叉验证"),
        ("results/inter/only32_ace_independent/", "A/C/E 独立标签验证"),
        ("results/inter/only32_abce_30f/", "BDRate、逐 QP 和选择率结果"),
    ], [4800, 4560], font_size=8.5,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])
    add_para(doc, "最终建议：以 cutoff 92 为默认硬件档，cutoff 89 仅作为更激进的可配置档；平台迁移验收以触发精度、误触发率、逐序列增量 BDRate 和最差序列四项共同决定。")

    # Structural audit against compact_reference_guide tokens.
    assert len(doc.sections) == 1
    sec = doc.sections[0]
    assert round(sec.left_margin / 914400, 3) == 1.0
    assert round(sec.right_margin / 914400, 3) == 1.0
    assert doc.styles["Normal"].font.name == "Calibri"
    for table in doc.tables:
        tbl_w = table._tbl.tblPr.find(qn("w:tblW"))
        assert tbl_w is not None and tbl_w.get(qn("w:w")) == "9360"
        grid = [int(node.get(qn("w:w"))) for node in table._tbl.tblGrid.findall(qn("w:gridCol"))]
        assert sum(grid) == 9360
    DOCX.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DOCX)
    print(DOCX)


if __name__ == "__main__":
    build_report()
