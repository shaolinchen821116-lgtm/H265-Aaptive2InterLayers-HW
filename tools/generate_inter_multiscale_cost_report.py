#!/usr/bin/env python3
"""Generate the P-frame multiscale and hierarchy-cost research report."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from generate_inter_only32_report import (
    BLUE,
    DARK_BLUE,
    INK,
    MUTED,
    add_code,
    add_numbered,
    add_numbering,
    add_para,
    configure_styles,
    fixed_table,
    heading,
    qn,
    set_font,
    set_repeat_page_number,
)


ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "docs" / "P帧多尺度与层次Cost两层选择_测试与训练报告_zh.docx"
FLOW = ROOT / "docs" / "assets" / "p_inter_multiscale_cost_flow.png"
MS_ROOT = ROOT / "results" / "inter" / "multiscale_2layer"
COST_ROOT = ROOT / "results" / "inter" / "hierarchy_cost_only"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def render_flowchart(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1680, 1180), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    bold_path = Path("C:/Windows/Fonts/msyhbd.ttc")
    font = ImageFont.truetype(str(font_path), 29)
    small = ImageFont.truetype(str(font_path), 25)
    bold = ImageFont.truetype(str(bold_path), 30)

    def box(x, y, w, h, text, fill="#E8EEF5", outline="#2E74B5", strong=False):
        draw.rounded_rectangle((x, y, x + w, y + h), radius=18,
                               fill=fill, outline=outline, width=4)
        use = bold if strong else font
        bounds = draw.multiline_textbbox((0, 0), text, font=use,
                                         spacing=7, align="center")
        tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
        draw.multiline_text((x + (w - tw) / 2, y + (h - th) / 2), text,
                            font=use, fill="#0B2545", spacing=7, align="center")

    def arrow(x1, y1, x2, y2, label=""):
        import math
        draw.line((x1, y1, x2, y2), fill="#415A77", width=5)
        angle = math.atan2(y2 - y1, x2 - x1)
        for delta in (2.55, -2.55):
            draw.line((x2, y2, x2 + 21 * math.cos(angle + delta),
                       y2 + 21 * math.sin(angle + delta)), fill="#415A77", width=5)
        if label:
            draw.text(((x1 + x2) / 2 + 8, (y1 + y2) / 2 - 36), label,
                      font=small, fill="#7A5A00")

    box(530, 25, 620, 90, "P 帧 CU32 根节点", strong=True)
    box(405, 165, 870, 120, "并行/复用 IME 探针\n1×CU32 + 4×CU16 + 16×CU8")
    box(80, 375, 680, 125, "mode 8：29 维整数特征\nSAD / 活动度 / MV 一致性 / QP")
    box(920, 375, 680, 125, "mode 9：层次 cost-only\nJ = SAD + sqrt(lambda) × MVD_bits")
    box(100, 590, 640, 110, "代价敏感 CART；cutoff 45",
        fill="#EAF4EA", outline="#3B7A57", strong=True)
    box(940, 590, 640, 110, "J32 < J8→32？",
        fill="#FFF4D6", outline="#B7791F", strong=True)
    box(160, 805, 520, 105, "高两层：CU32 + CU16")
    box(1000, 805, 520, 105, "低两层：CU16 + CU8")
    box(465, 1010, 750, 105, "各分支继续完成 FME、AMVP、Merge 与残差 RDO")
    arrow(840, 115, 840, 165)
    arrow(670, 285, 430, 375, "推荐")
    arrow(1010, 285, 1260, 375, "公式基线")
    arrow(420, 500, 420, 590)
    arrow(1260, 500, 1260, 590)
    arrow(420, 700, 420, 805, "低概率 < 45")
    arrow(650, 700, 1260, 805, "低概率 ≥ 45")
    arrow(1140, 700, 420, 805, "是：高")
    arrow(1380, 700, 1260, 805, "否：低")
    arrow(420, 910, 720, 1010)
    arrow(1260, 910, 960, 1010)
    draw.text((80, 1135),
              "I 帧不受 P 帧选层控制：intra32 / intra16 / intra8 始终全部开放。",
              font=small, fill="#4B5563")
    image.save(path, dpi=(180, 180))


def add_title_page(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    set_font(p.add_run("技术研究与复现报告"), size=11, bold=True, color=BLUE)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("P 帧多尺度两层选择与层次 Cost 基线"),
             size=23, bold=True, color=INK)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(18)
    set_font(p.add_run("完整 x265 实现、测试结果、数据格式与训练方法"),
             size=14, color=DARK_BLUE)
    fixed_table(doc, ["项目", "内容"], [
        ("当前推荐", "mode 8：多尺度代价敏感 CART，cutoff 45"),
        ("公式基线", "mode 9：J32 与 4×min(J8) 层次 cost-only"),
        ("测试集合", "Class A/B/C/E；17 序列；每点 1I+29P"),
        ("码率点", "固定 QP 22 / 27 / 32 / 37"),
        ("I 帧保护", "intra32 / intra16 / intra8 全部开放"),
        ("源码状态", "仓库 x265/ 为已合入研究改动的完整源码"),
        ("日期", "2026-08-26"),
    ], [2200, 7160], font_size=9.5,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    set_font(p.add_run("结论摘要"), size=13, bold=True, color=BLUE)
    add_para(doc, "mode 8 在 ABCE 17 序列上的平均 BD-rate 为 +0.966%，最差 Kimono1 +1.606%；冻结的 Class B 模型在 A/C/E 独立数据上的决策正确率为 84.834%。")
    add_para(doc, "mode 9 严格实现指定公式，在 Class B 上平均 +1.659%；其 58.073% 的低两层选择率明显高于 RDO 标签的 35.894%，说明 4×min(J8) 会低估兄弟块差异大的低层路径。")
    add_para(doc, "因此 mode 9 保留为 cost-rooted 混合训练的根判据，不作为当前发布配置；所有结论均来自短序列研究，正式硬件定型仍需更长序列验证。")
    doc.add_page_break()


def build_report() -> None:
    render_flowchart(FLOW)
    doc = Document()
    configure_styles(doc)

    header = doc.sections[0].header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_font(header.add_run("H265 Adaptive Inter Layers · P 帧多尺度与层次 Cost"),
             size=9, bold=True, color=MUTED)
    footer = doc.sections[0].footer.paragraphs[0]
    set_repeat_page_number(footer)
    add_title_page(doc)

    heading(doc, "1. 研究目标与边界", 1)
    add_para(doc, "目标是在硬件友好的 PME→IME→FME 框架中，只使用当前 CTU 的搜索结果、QP 及其派生 sqrt(lambda)，在 P 帧根节点选择高两层 CU32/CU16 或低两层 CU16/CU8；I 帧继续开放全部三层。")
    items = add_numbering(doc)
    for text in (
        "CU、PU、TU 按正方形层级对齐；本阶段只研究 32×32、16×16、8×8。",
        "PME 在 1/4 下采样图像上搜索 [-32,32]×[-28,28]，传给 IME 时乘 4 对齐 full-pel。",
        "IME 在重构参考上搜索 [-12,12]×[-12,12]；FME 以 AMVP 为 attractor。",
        "选层门控只裁剪递归层级，不替代本层 AMVP、Merge、残差与最终 RDO。",
        "训练标签来自完整三层 mode 7 的最终 RDO 叶层；边界不完整 CTU 使用安全回退。",
    ):
        add_numbered(doc, items, text)
    doc.add_picture(str(FLOW), width=Inches(6.35))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_page_break()
    heading(doc, "2. 编码与测试配置", 1)
    fixed_table(doc, ["项目", "配置"], [
        ("结构", "每点 30 帧：第 1 帧 I，随后 29 帧 P；B 帧关闭"),
        ("码控", "固定 QP 22 / 27 / 32 / 37；BD-rate 使用 Y-PSNR"),
        ("x265", "preset medium；tune zerolatency；ref=1；frame-threads=1"),
        ("块结构", "CTU32；min CU8；禁止 rect/amp；正方形 PU；max TU32"),
        ("测试集", "Class A 2、B 5、C 4、E 6，共 17 个序列"),
        ("基线", "同一硬件 HME 的 P 帧完整三层；I 帧三层始终全开"),
    ], [2400, 6960], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])
    add_code(doc, [
        "--preset medium --tune zerolatency --qp <QP> --frames 30",
        "--bframes 0 --ref 1 --frame-threads 1 --no-scenecut",
        "--ctu 32 --min-cu-size 8 --no-rect --no-amp --max-tu-size 32",
        "--hw-hme --hw-hme-pme-range 32,28 --hw-hme-ime-range 12,12",
        "--hw-hme-inter-layers 8 --hw-hme-layer-cutoff 45",
    ])

    heading(doc, "3. mode 8：多尺度两层决策", 1)
    add_para(doc, "每个 CU32 根节点复用或并行获得 1 个 CU32、4 个 CU16、16 个 CU8 的 IME 探针。由这些结果构造 29 个整数特征，主要包括：QP；各层 SAD 的均值、范围和平均绝对偏差；SAD 层间收益；原始像素活动度；MV 的一致性、跨度及边界命中数。")
    fixed_table(doc, ["特征组", "数量/示例", "硬件含义"], [
        ("QP", "1", "直接输入；树阈值隐式学习 Qstep 变化"),
        ("SAD 统计", "均值/最小/最大/MAD", "加减、比较、移位"),
        ("层间收益", "32↔16、16↔8", "固定点比值或交叉乘"),
        ("纹理活动", "水平/垂直差分", "源像素绝对差累加"),
        ("MV 一致性", "均值、跨度、MAD", "坐标差绝对值"),
        ("边界信息", "搜索窗边界命中数", "计数器"),
    ], [2100, 2800, 4460], font_size=8.8,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT] * 3)
    add_para(doc, "训练采用 Class B 按序列留一交叉验证的代价敏感整数 CART：最大深度 7、最小叶节点 256、低层标签权重 1.5。运行时只保留整数比较；cutoff 45 用于降低把真实低层误选为高层的风险。")

    heading(doc, "4. mode 8 训练与数据格式", 1)
    train_num = add_numbering(doc)
    for text in (
        "用 mode 7 编码完整三层，输出每 CTU 一行 INTERLAYERMS；同一行保存 29 个特征、leaf32/leaf16/leaf8 和 oracle 标签。",
        "剔除 valid=0 的右/下边界不完整 CTU；按序列分组，避免同一序列样本同时出现在训练和验证中。",
        "运行 train_inter_multiscale_tree.py 训练并扫描 cutoff；输出 JSON、可读文本、C/C++ 头文件、阈值表和逐序列混淆矩阵。",
        "使用冻结的 Class B 头文件，在 A/C/E mode 7 日志上运行 evaluate_inter_multiscale_tree.py，禁止重新拟合。",
        "将候选头文件编入 mode 8，完成真实 30 帧 BD-rate；最终阈值必须同时满足平均值和最差序列约束。",
    ):
        add_numbered(doc, train_num, text)
    add_code(doc, [
        "python experiments/inter_hw_hme/train_inter_multiscale_tree.py ^",
        "  D:/work/classb_mode7/runs.csv --output D:/work/multiscale_tree ^",
        "  --max-depth 7 --min-leaf 256 --low-weight 1.5",
        "python experiments/inter_hw_hme/evaluate_inter_multiscale_tree.py ^",
        "  D:/work/ace_mode7/runs.csv --model D:/work/multiscale_tree/inter_multiscale_tree.json ^",
        "  --cutoff 45 --output D:/work/ace_accuracy.csv",
    ])
    fixed_table(doc, ["关键输出", "用途"], [
        ("inter_multiscale_tree.json/.txt", "复核树结构、阈值与叶节点概率"),
        ("inter_multiscale_gate_model.h", "x265 与硬件/便携 C 集成"),
        ("inter_multiscale_thresholds_cv.csv", "cutoff 的准确率、召回率和误判率"),
        ("inter_multiscale_sequence_cv.csv", "逐序列泛化风险"),
        ("independent_model_accuracy_c45.csv", "A/C/E 固定模型独立验证"),
        ("runs.csv / bd_rate_summary.csv", "真实码流、PSNR、选层率与 BD-rate"),
    ], [3900, 5460], font_size=8.8,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])

    doc.add_page_break()
    heading(doc, "5. mode 8 决策正确率", 1)
    fixed_table(doc, ["数据", "样本", "准确率", "平衡准确率", "低层召回", "误高/低标签"], [
        ("Class B LOO，cutoff 45", "435,600", "77.731%", "79.305%", "84.880%", "15.120%"),
        ("A/C/E 独立，cutoff 45", "652,960", "84.834%", "84.934%", "85.394%", "14.606%"),
    ], [2050, 1400, 1450, 1600, 1450, 1410], font_size=8.6,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])
    add_para(doc, "正确率是与完整三层最终叶层标签的一致率，并不等价于 BD-rate。模型发布必须以真实编码结果为准，因为少量高代价误判可能比大量低风险误判更重要。")

    heading(doc, "6. mode 8 ABCE 真实 BD-rate", 1)
    ms_bd = read_csv(MS_ROOT / "abce_c45_30f" / "bd_rate_summary.csv")
    seq_rows = [(r["class"].replace("Class", ""), r["sequence"],
                 f'{float(r["bd_rate_y_psnr_pct"]):+.3f}%')
                for r in ms_bd if r["class"] != "All"]
    fixed_table(doc, ["Class", "序列", "相对完整三层 BD-rate"], seq_rows,
                [1200, 4800, 3360], font_size=8.4,
                aligns=[WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT,
                        WD_ALIGN_PARAGRAPH.RIGHT])
    doc.add_page_break()
    fixed_table(doc, ["Class", "序列数", "平均 BD-rate", "最差"], [
        ("A", "2", "+1.010%", "+1.350%"),
        ("B", "5", "+1.050%", "+1.606%"),
        ("C", "4", "+0.767%", "+1.294%"),
        ("E", "6", "+1.014%", "+1.405%"),
        ("全部", "17", "+0.966%", "+1.606%"),
    ], [2100, 1500, 2700, 3060], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT,
                        WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT])
    add_para(doc, "mode 8 的实际高/低两层选择率为 55.283% / 44.717%。相对旧 CU32-only 特征树的 +1.498%，平均改善 0.532 个百分点；但 Kimono1 仍超过 1%，不能声称所有运动场景都满足 <1%。")

    heading(doc, "7. mode 9：指定层次 Cost 的精确定义", 1)
    add_para(doc, "所有 rate 项均使用同一个 QP 对应的 sqrt(lambda)，以 Q8 定点实现：R(bits)=(sqrtLambdaQ8×bits+128)>>8。MVD_bits 以各层 AMVP 为 attractor 计算，包含符号和幅度的运动矢量差码长。")
    add_code(doc, [
        "J8[i]      = SAD8[i] + R(MVD_bits8[i])",
        "J16[g]     = 4 * min(J8[4*g + 0 .. 4*g + 3])",
        "J8_to_32   = sum(g=0..3, J16[g]) + R(5)   // split bits: 32→16 + 4×16→8",
        "J32        = SAD32 + R(MVD_bits32) + R(1) // one non-split flag",
        "if (J32 < J8_to_32) select high2; else select low2;",
    ])
    add_para(doc, "QPstep 与 sqrt(lambda) 已显式进入判据：QP 每增加 6，Qstep 约翻倍；sqrt(lambda) 使 MVD 与 split bits 的权重随 QP 增长。这里没有使用最终残差 bits，也不使用纹理或跨层 MV 修正规则，确保该实验只回答纯 cost 判据本身的效果。")

    doc.add_page_break()
    heading(doc, "8. mode 9 分类与真实编码结果", 1)
    cost_acc = read_csv(COST_ROOT / "classb_accuracy_12f" / "cost_accuracy.csv")
    all_cost = next(r for r in cost_acc if r["sequence"] == "All")
    fixed_table(doc, ["指标", "结果"], [
        ("有效样本", f'{int(float(all_cost["samples"])):,}'),
        ("RDO 低层标签率", f'{float(all_cost["oracle_low_pct"]):.3f}%'),
        ("cost-only 低层选择率", f'{float(all_cost["selected_low_pct"]):.3f}%'),
        ("判断正确率", f'{float(all_cost["accuracy_pct"]):.3f}%'),
        ("平衡准确率", f'{float(all_cost["balanced_accuracy_pct"]):.3f}%'),
        ("低层召回率", f'{float(all_cost["low_recall_pct"]):.3f}%'),
        ("真实高层误选低层", f'{float(all_cost["false_low_pct_of_high"]):.3f}%'),
        ("平均 J8→32 / J32", f'{float(all_cost["mean_cost8_over_cost32"]):.6f}'),
    ], [4700, 4660], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT])
    cost_bd = read_csv(COST_ROOT / "classb_rd_30f" / "bd_rate_summary.csv")
    fixed_table(doc, ["序列", "相对完整三层 BD-rate"], [
        (r["sequence"], f'{float(r["bd_rate_y_psnr_pct"]):+.3f}%')
        for r in cost_bd if r["class"] != "All"
    ] + [("Class B 平均", "+1.659%")], [6000, 3360], font_size=9,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT])
    add_para(doc, "主要失配不是 sqrt(lambda) 缺失，而是 4×min(J8) 用一个最佳 8×8 代表整个 16×16。当同组四个 8×8 的纹理、SAD 或 MV 不一致时，它会系统性低估低层路径，造成 42.418% 的真实高层样本误选低层；Cactus 和 Kimono1 最明显。")

    heading(doc, "9. 后续 cost-rooted 混合训练", 1)
    add_para(doc, "下一阶段保留用户指定 cost 比较作为强制根节点，在其“偏高/偏低”两侧分别训练小型修正子树。附加特征只使用已有的 QP、SAD、活动度和 MV 一致性，不引入最终编码 bits 或其他编码器状态。")
    fixed_table(doc, ["修正特征", "目的", "硬件实现"], [
        ("J8→32/J32 分段", "衡量 cost 判决置信区间", "交叉乘比较，避免除法"),
        ("四组 J16 的 range/MAD", "识别 4×min 的兄弟块低估", "减法、绝对值、累加"),
        ("8×8/16×16 MV range/MAD", "识别分裂层运动不一致", "坐标差和计数"),
        ("SAD 层间收益", "区分纹理细节和真实运动收益", "固定点比较"),
        ("QP / sqrtLambdaQ8", "学习 Qstep 与率项权重变化", "查表输入"),
    ], [2600, 3800, 2960], font_size=8.5,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT] * 3)
    add_code(doc, [
        "python experiments/inter_hw_hme/train_inter_hybrid_cost_tree.py ^",
        "  D:/work/classb_mode7/runs.csv --output D:/work/hybrid_cost_tree ^",
        "  --max-depth 7 --min-leaf 256 --low-weight 1.5",
    ])
    add_para(doc, "Class B 留一训练已经完成：cutoff 45 的正确率为 76.294%、平衡正确率 78.137%、低层召回率 84.668%。该分类结果低于 mode 8 的 77.731%，而且尚未完成独立 A/C/E 和真实 BD-rate，因此只作为候选训练产物交付，不能替换 mode 8。")

    heading(doc, "10. I 帧保护与一致性验证", 1)
    add_para(doc, "P 帧层级模式非零时，I_SLICE 路径仍强制使用完整 intra32/intra16/intra8。BasketballDrive 第一帧 QP32 的 mode 0 与 mode 8 码流均为 47,355 bytes，SHA-256 完全相同：")
    add_code(doc, ["34FA853EA0790F6610E2AA9970E517EE2005003C46190A8524E1916648B857BC"])
    add_para(doc, "这验证了新 P 帧门控没有改变 I 帧层级；它不证明其他配置或所有序列逐位相同，因此迁移平台仍需保留 I 帧回归测试。")

    doc.add_page_break()
    heading(doc, "11. 完整源码构建、运行与复现", 1)
    add_para(doc, "仓库根目录的 x265/ 是完整源码快照，已直接合入本研究改动；x265_overlay/ 仅用于向其他已有 x265 树人工移植。构建产物、YUV、码流和逐 CTU 大日志不进入仓库。")
    add_code(doc, [
        "cmake -S x265/source -B x265/build/release -G Ninja ^",
        "  -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF",
        "cmake --build x265/build/release --parallel",
        "x265/build/release/x265.exe --help",
    ])
    add_code(doc, [
        "# 完整三层标签与特征采集",
        "x265.exe ... --hw-hme --hw-hme-inter-layers 7 --hw-hme-stats",
        "# 推荐的多尺度树",
        "x265.exe ... --hw-hme --hw-hme-inter-layers 8 --hw-hme-layer-cutoff 45",
        "# 指定层次 cost-only 基线",
        "x265.exe ... --hw-hme --hw-hme-inter-layers 9",
    ])
    fixed_table(doc, ["模式", "作用"], [
        ("0", "P 帧完整三层；anchor"),
        ("1 / 2", "强制高两层 / 强制低两层"),
        ("3–6", "历史 CU32 特征树、标签和 CU32-only 研究"),
        ("7", "完整三层，并输出 INTERLAYERMS / INTERLAYERCOST 标签日志"),
        ("8", "29 维多尺度 CART；当前推荐 cutoff 45"),
        ("9", "J32 与 4×min(J8) 层次 cost-only"),
    ], [1500, 7860], font_size=8.8,
                aligns=[WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT])

    doc.add_page_break()
    heading(doc, "12. 文件索引与结论边界", 1)
    fixed_table(doc, ["路径", "内容"], [
        ("x265/", "已合入所有研究改动的完整 x265 源码"),
        ("x265_overlay/", "便于向其他平台逐文件移植的改动集"),
        ("experiments/inter_hw_hme/", "采集、分析、训练、评估和编码批处理脚本"),
        ("experiments/inter_hw_hme/portable_c/", "面向硬件/其他平台的 C99 参考"),
        ("results/inter/multiscale_2layer/", "mode 8 训练、独立验证和 ABCE 结果"),
        ("results/inter/hierarchy_cost_only/", "mode 9 分类和 Class B 真实编码结果"),
        ("docs/REPRODUCE_zh.md", "从构建、采集到训练和 BD-rate 的命令说明"),
        ("README_zh.md", "仓库总入口、模式和结论摘要"),
    ], [4800, 4560], font_size=8.4,
                aligns=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT])
    add_para(doc, "当前可发布结论是：mode 8 在短序列 ABCE 平均损失低于 1%，但最差序列仍高于 1%；mode 9 验证了 sqrt(lambda) 和 split bits 的作用，也暴露了 4×min 聚合的结构性偏差。下一步应优先验证 cost-rooted 修正树，并将测试扩展到 100–300 帧、场景切换和更多运动类型。")

    # Structural audit for compact_reference_guide.
    assert len(doc.sections) == 1
    section = doc.sections[0]
    assert round(section.left_margin / 914400, 3) == 1.0
    assert round(section.right_margin / 914400, 3) == 1.0
    assert doc.styles["Normal"].font.name == "Calibri"
    for table in doc.tables:
        width = table._tbl.tblPr.find(qn("w:tblW"))
        assert width is not None and width.get(qn("w:w")) == "9360"
        grid = [int(node.get(qn("w:w")))
                for node in table._tbl.tblGrid.findall(qn("w:gridCol"))]
        assert sum(grid) == 9360
    DOCX.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DOCX)
    print(DOCX)


if __name__ == "__main__":
    build_report()
