# -*- coding: utf-8 -*-
"""生成《旺店通功能模块分类与核心业务影响分析》Word 文档（简洁版：划分模块 + 理由）。
纯黑色文字，无配色无底色。基于《功能分类表.xlsx》的 15 个一级类目。
"""
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

BLACK = RGBColor(0, 0, 0)

doc = Document()

# 默认字体：黑色、小四
style = doc.styles["Normal"]
style.font.name = "宋体"
style.font.size = Pt(12)
style.font.color.rgb = BLACK
# 西文部分也用同色
style.element.rPr.rFonts.set(__import__("docx").oxml.ns.qn("w:eastAsia"), "宋体")

def set_black(run):
    run.font.color.rgb = BLACK

def heading(text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_black(run)
    return p

def para(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    set_black(r)
    return p

def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run(text)
    set_black(r)
    return p

# ---- 标题 ----
title = doc.add_heading("旺店通功能模块分类与核心业务影响分析", level=0)
for r in title.runs:
    set_black(r)

para("分类依据：以《功能分类表.xlsx》的 15 个一级类目为准。结合旺店通 ERP「订单履约」核心链路"
     "（对接 → 商品 → 订单 → 仓储 → 售后 → 账款，底垫登录/配置），对每个模块的核心度进行分层，"
     "并说明划分理由。")

# ---- 一、模块分层总览 ----
heading("一、模块分层总览", 1)
para("按「出问题是否影响整体业务进展」将 15 个模块分为三层：")
bullet("P0 核心链路：任一异常直接阻断履约，整体业务停摆。")
bullet("P1 重要支撑：影响资金/体验/可用性，但非即时全停。")
bullet("P2 辅助扩展：影响面局部，或仅属特定业务模式/决策支撑。")

# ---- 二、各模块划分与理由 ----
heading("二、各模块划分与理由", 1)

# 数据：(模块, 分层, 理由)
rows = [
    # P0
    ("对接", "P0 核心", "平台订单下载、库存同步、API 对接的源头。出问题则无单可处理、库存超卖，整条链路断流。"),
    ("商品", "P0 核心", "货品匹配、SKU、组合装是基础数据。匹配错误导致订单无法正确生成、发货错货。"),
    ("订单", "P0 核心", "整个 ERP 的中心交易环节。审单/打单/发货卡住，商家直接无法履约。"),
    ("仓储", "P0 核心", "库存同步（防超卖）、出入库、分拣发货。库存不准或出不了库，发不出货、超卖赔款。"),
    ("配置", "P0 核心", "店铺绑定、快递/仓库信息、权限。配置错误会连累整条链路（如快递模板错导致打不出单）。"),
    # P1
    ("登录", "P1 重要", "统一入口，挂了全员进不去，属「全有或全无」的高可用项。"),
    ("售后", "P1 重要", "退换、拦截、无头件。影响客户体验与退款损失，属下游，不阻断当日发货。"),
    ("采购", "P1 重要", "供应商、采购单、智能预警。影响后续库存补给，属经营持续性问题。"),
    ("账款", "P1 重要", "应收应付、结算、发票。资金侧，错漏影响财务但非即时致命。"),
    # P2
    ("报表", "P2 辅助", "决策/分析类，出问题不影响发货。"),
    ("分享", "P2 辅助", "资源共享，不影响履约主流程。"),
    ("铺货", "P2 辅助", "特定业务模式（铺货到多平台），仅影响对应商户群体。"),
    ("档口", "P2 辅助", "批发档口拿货业务，垂直场景，仅影响对应商户。"),
    ("供分销", "P2 辅助", "分销网络/一件代发，业务模式扩展，局部影响。"),
    ("跨境", "P2 辅助", "跨境业务（TEMU/亚马逊等），垂直场景，仅影响跨境商户。"),
]

table = doc.add_table(rows=1, cols=3)
table.style = "Table Grid"
table.alignment = WD_TABLE_ALIGNMENT.CENTER
hdr = table.rows[0].cells
hdr[0].text = "模块"
hdr[1].text = "分层"
hdr[2].text = "划分理由"
for c in hdr:
    for p in c.paragraphs:
        for r in p.runs:
            set_black(r)
            r.bold = True

for name, layer, reason in rows:
    cells = table.add_row().cells
    cells[0].text = name
    cells[1].text = layer
    cells[2].text = reason
    for c in cells:
        for p in c.paragraphs:
            for r in p.runs:
                set_black(r)

# ---- 三、结论 ----
heading("三、结论", 1)
para("真正「影响整体业务进展」的是 P0 五模块（对接、商品、订单、仓储、配置）及登录入口——"
     "任一异常即整条履约链停摆。P1（售后、采购、账款）影响资金与体验但非即时阻断；"
     "P2（报表、分享、铺货、档口、供分销、跨境）多为局部或持续性影响。")
para("对智能处理 Bot 的启示：分类与可靠性打分等 AI 环节应优先保障 P0 模块的准确性，"
     "并在知识库中对核心模块给予更高关注度。")

out = r"../docs/旺店通模块分类与核心度说明.docx"
doc.save(out)
print("saved:", out)
