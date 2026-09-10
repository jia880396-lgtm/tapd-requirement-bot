# -*- coding: utf-8 -*-
"""生成《TAPD 需求智能处理 Agent — 各模块判断标准梳理》Word 文档。"""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = r"../docs/需求智能处理各模块判断标准梳理.docx"

doc = Document()

# ---- 基础样式 ----
normal = doc.styles["Normal"]
normal.font.name = "Microsoft YaHei"
normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
normal.font.size = Pt(10.5)

PRIMARY = RGBColor(0x16, 0x5D, 0xFF)


def set_cell_bg(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def add_title(text):
    p = doc.add_heading(level=0)
    run = p.add_run(text)
    run.font.color.rgb = PRIMARY
    run.font.size = Pt(22)
    return p


def h1(text):
    p = doc.add_heading(level=1)
    r = p.add_run(text)
    r.font.color.rgb = PRIMARY
    return p


def h2(text):
    return doc.add_heading(text, level=2)


def h3(text):
    return doc.add_heading(text, level=3)


def para(text, bold=False, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    return p


def bullet(text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.add_run(text)
    return p


def numbered(text):
    p = doc.add_paragraph(style="List Number")
    p.add_run(text)
    return p


def make_table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, htext in enumerate(headers):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(htext)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.size = Pt(10)
        set_cell_bg(hdr[i], "165DFF")
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.size = Pt(9.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    return t


# ===================== 封面 / 前言 =====================
add_title("TAPD 需求智能处理 Agent\n各模块判断标准梳理")
para("（基于当前后端代码实现：reliability_scorer / duplicate_detector / classifier / prd_analyzer 及配套 prompts、知识库、配置项）", italic=True)
para("")
para("文档说明：", bold=True)
bullet("本文逐模块梳理「输入、判断流程、判分标准、通过/不通过规则、当前默认参数」，所有内容均取自源码与提示词原文，非推测。")
bullet("配置项存在两层：『系统默认值』（config.py 环境变量）与『用户业务配置覆盖』（user_settings，用户在『我的业务配置』内可逐字段覆盖）。下文『当前默认参数』指系统默认值，实际以用户覆盖为准。")
bullet("四个模块分别为：① 需求可靠性打分 ② 重复需求识别 ③ 需求分类 ④ PRD 有效性分析。")

doc.add_page_break()

# ===================== 一、需求可靠性打分 =====================
h1("一、需求可靠性打分（reliability_scorer）")

h2("1.1 处理流程")
numbered("输入：UserRequirementJob.description（从 TAPD 客户问题描述提取）。")
numbered("调用 DeepSeek score_reliability（prompt：prompts.RELIABILITY_PROMPT，注入 get_reliability_context 精简知识库）。")
numbered("写回：reliability_score / reliability_detail（含 dimensions + reason）/ supplemental_questions / status=\"scored\"。")
numbered("判定：total_score >= reliability_threshold（默认 60）为『通过』；仅当未达标时才记录补充问题，达标则 supplemental_questions 置空。")

h2("1.2 评分维度与分值（满分 100）")
make_table(
    ["评分维度", "分值", "判分要点"],
    [
        ["信息完整度", "30", "是否包含 客户标识 / 业务场景 / 问题描述 / 期望效果"],
        ["描述清晰度", "30", "描述是否清晰、能否让人理解问题所在"],
        ["可实现性", "20", "是否明确到可进入产品评估阶段"],
        ["业务价值", "20", "是否有合理的业务动机"],
    ],
    widths=[1.6, 0.8, 4.6],
)

h2("1.3 各维度评分标准（分档，prompt 原文）")
h3("信息完整度（30 分）")
bullet("5 分：模板文字未替换，客户信息和业务场景都是模板占位符")
bullet("15 分：有客户标识或业务场景，但问题描述缺失或过于简略")
bullet("22 分：客户标识、业务场景、问题描述基本齐全，能理解问题")
bullet("28 分：上述四项齐全且有具体单号/租户等定位信息")
bullet("30 分：信息完整，问题表述清晰具体")
h3("描述清晰度（30 分）")
bullet("5 分：需求极其模糊（『希望更智能』『优化体验』）")
bullet("15 分：有明确方向，能大致理解诉求")
bullet("22 分：问题清楚，能理解在哪个环节遇到了什么困难")
bullet("28 分：问题清楚，有具体功能点或操作环节")
bullet("30 分：问题描述精确，有明确的功能点和操作环节")
h3("可实现性（20 分）")
bullet("5 分：需求完全不明确，无法理解要做什么")
bullet("12 分：需求方向明确，范围较大但可进入产品评估")
bullet("16 分：需求明确，范围可控，可进入产品评估")
bullet("20 分：需求明确，有具体调整点")
h3("业务价值（20 分）")
bullet("5 分：完全看不出为什么要提这个需求")
bullet("12 分：有合理动机（解决某类客户问题/优化流程）")
bullet("16 分：动机明确，能看出对客户或业务有帮助")
bullet("20 分：动机明确，有量化或具体客户影响")

h2("1.4 通过判定与补充问题")
para("通过线：total_score >= reliability_threshold（默认 60）；pass 字段据此返回 true/false。", bold=True)
para("补充问题（仅未达标时生成，problem_scenario 聚焦模式下）：", bold=True)
bullet("只问最关键的 2–3 个问题（受 question_max_count 控制，默认 3，不超过上限）；")
bullet("只追问问题场景本身：客户在什么场景下遇到了什么问题；")
bullet("禁止追问技术实现细节（如『对接方式是 API 还是……』）；")
bullet("禁止追问产品方案（如『涉及哪些平台』『具体调整点是什么』『验收标准』）；")
bullet("禁止追问量化数据（如『影响多少客户』『节省多少时间』）；")
bullet("问题要简短直接，让提交人容易回答。")
para("正确示例：『请补充具体是哪个客户（租户账号）遇到了这个问题』『请描述在哪个页面进行什么操作时出现了什么问题』。", italic=True)
para("错误示例（禁止）：『请说明对接的具体技术方式』『请提供验收标准和调整点』『请说明影响多少客户、节省多少时间』。", italic=True)

h2("1.5 松紧度策略（scoring_strictness）")
make_table(
    ["档位", "评分原则（代码注入）", "对『截图/量化数据』的态度"],
    [
        ["loose（默认）", "宽松评分：只要能理解『谁+场景+问题+期望效果』就给及格以上", "不因缺截图扣分；不因缺量化数据过度扣分"],
        ["standard", "标准评分：综合判断四维度；缺关键业务信息适当扣", "不因缺截图扣，但缺关键业务信息适当扣"],
        ["strict", "严格评分：必须信息完整+清晰+明确价值+技术可行", "缺截图/量化数据/具体单号等关键信息应适当扣分"],
    ],
    widths=[1.2, 3.4, 2.4],
)

h2("1.6 注入知识（get_reliability_context，精简版）")
bullet("业务背景：旺店通 ERP 产品体系、核心模块与对接平台清单；")
bullet("需求描述模板：提交人需填写【客户信息】【业务场景】【遇到的问题/截图】【希望实现的效果】【需求价值】；")
bullet("低质量特征（降分）：模板文字未替换、缺单号/租户/截图、需求模糊、需求价值为空；")
bullet("高质量特征（加分）：具体客户账号、明确模块路径、具体单号、量化影响；")
bullet("打分校准：四个维度各档分值锚点（见 1.3，精简版给出 ≤5/10/15/20/25/30 等锚点）；")
bullet("关键业务术语：抓单/审单/拆单/合单/WMS/PDA/委外入库/商家编码/售后单/店铺授权/铺货/数电票/对账/档口 等。")

h2("1.7 当前默认参数")
make_table(
    ["参数", "默认值", "含义"],
    [
        ["reliability_threshold", "60", "可靠性达标阈值，低于则未达标并生成补充问题"],
        ["question_max_count", "3", "补充问题数量上限（2–3）"],
        ["question_focus", "problem_scenario", "补充问题聚焦方向（问题场景 / 全量）"],
        ["scoring_strictness", "loose", "评分松紧度 loose/standard/strict"],
    ],
    widths=[2.2, 1.2, 3.6],
)

doc.add_page_break()

# ===================== 二、重复需求识别 =====================
h1("二、重复需求识别（duplicate_detector）")

h2("2.1 处理流程（两段式，见 routers/user_requirements.py 组合任务）")
numbered("阶段 1「重复识别」：本次新增需求按 TAPD 创建时间正序处理（早提交的保留）；每条的对比库 = 历史库（duplicate_history_limit 默认 500 条，按 tapd_created desc 取最近）+ 本次已确认『不重复』的新需求（kept_records）。")
numbered("阶段 2「打分」：仅对阶段 1 判定为非重复的需求进行可靠性打分。")
numbered("单条识别：排除自身 story_id → 格式化历史（每条取描述前 200 字）→ 调 detect_duplicate → 后处理 → 写回 is_duplicate / duplicate_with / similarity / duplicate_detail / status。")

h2("2.2 判定标准（prompts.DUPLICATE_DETECTION_PROMPT 原文）")
para("判定为重复（is_duplicate=true）：", bold=True)
bullet("核心功能诉求一致，仅客户信息不同；")
bullet("平台 + 模块 + 操作 三要素相同；")
bullet("同一功能点的不同表述（如『货品页面布局优化』vs『商品页面 UI 调整』）。")
para("相似不重复（is_duplicate=false, similarity > 0.5）：", bold=True)
bullet("相关但解决不同问题；")
bullet("同模块但不同功能点。")
para("不重复（is_duplicate=false, similarity < 0.5）：", bold=True)
bullet("完全不同的需求。")

h2("2.3 识别技巧（prompt 内）")
bullet("忽略客户信息：不同客户提交的同类需求算重复（核心诉求一致即可）；")
bullet("关注功能点：比较核心功能诉求，而非表述方式；")
bullet("模块归类：先判断需求所属模块，同模块内重点比较；")
bullet("操作类型：新增/优化/修复 是不同操作类型，但同操作类型+同功能点算重复。")

h2("2.4 LLM 返回字段与代码层后处理规则")
para("LLM 返回 JSON：is_duplicate / duplicate_with（需求 ID 列表）/ similarity（0–1）/ duplicate_type / reason。", bold=True)
para("代码后处理（duplicate_detector.py）：", bold=True)
bullet("剔除结果中的自身 story_id（避免匹配到自己）；")
bullet("若过滤后 duplicate_with 为空 → 强制 is_duplicate=False，且 similarity 封顶为 0.7；")
bullet("当 is_duplicate 为真 → status 置为 \"duplicate\"；")
bullet("duplicate_detail 取前 3 条，从历史库回填标题（二次校验自身 ID，未命中则标题留空）。")
para("已知风险（影响效果）：", bold=True, italic=True)
bullet("对比库把最多 500 条历史整段塞进一个 prompt（每条含标题+200 字描述），整体超长易超出模型上下文，导致后段历史被忽略、重复漏判；")
bullet("similarity 仅用于展示，代码无门槛校验（prompt 内『similarity>=0.8 为重复』与判定标准自相矛盾，且未被代码强制执行）；")
bullet("每条新需求都重复携带整份历史发起一次 LLM 调用，成本高且易溢出。")

h2("2.5 当前默认参数")
make_table(
    ["参数", "默认值", "含义"],
    [
        ["duplicate_history_limit", "500", "重复识别时拉取的最近历史需求条数"],
        ["历史描述截断", "200 字", "每条历史需求描述取前 200 字送入 prompt"],
        ["对比库顺序", "tapd_created desc", "历史库按创建时间倒序取最近 N 条"],
    ],
    widths=[2.4, 1.2, 3.4],
)

doc.add_page_break()

# ===================== 三、需求分类 =====================
h1("三、需求分类（classifier）")

h2("3.1 处理流程")
numbered("拉取 TAPD 中 story_status_filter（默认 status_2）状态的需求；")
numbered("跳过已分类（Classification 表已有记录）的需求；")
numbered("调用 LLM 分类（system_prompt 约束 + 分类树/术语表/跨模块规则）；")
numbered("写回 TAPD 评论（含 一级/二级/置信度/依据）；")
numbered("按 resolve_owner(category_l1, category_l2) 分配处理人（若开启自动派单）。")
para("LLM 调用参数：temperature=0.1，max_tokens=800，response_format=json_object，失败重试 3 次（间隔 1.5×n 秒）。", italic=True)

h2("3.2 分类体系（classification_kb.CATEGORY_TREE）")
para("共 24 个一级分类，部分带二级。一级分类列表：", bold=True)
para("登录、订单、商品、仓储、售后、采购、报表、账款、分享、配置、铺货、档口、供分销、跨境、对接（其中『报表/铺货/供分销』等为无二级的扁平类）。", )
para("带二级的代表：", bold=True)
bullet("订单：订单自动策略 / 订单手动操作 / 订单打印 / 订单信息；")
bullet("商品：平台货品 / 货品匹配 / 系统规格 / 组合装 / 云仓货品；")
bullet("仓储：库存查询 / 库存同步 / 入库管理 / 出库管理 / 仓库盘点 / 生产加工 / 调拨管理 / 委外出入库管理 / 货品验货 / 工作量登记 / 包裹称重；")
bullet("售后：售后单自动策略 / 售后单手动操作 / 售后单信息 / 快递拦截 / 智能退货入库 / 快速登记 / 无头件管理；")
bullet("采购：供应商 / 供应商货品 / 采购单 / 采购退货单 / 采购申请单 / 已售采购 / 采购智能预警；")
bullet("账款：交易对象 / 应收应付 / 收款付款 / 结算账户 / 资金流水 / 费用账单 / 发票管理；")
bullet("配置：绑定店铺 / 快递管理 / 仓库信息维护 / 非物流单模板 / 快递单模板 / 货区货位 / 货位分组 / 权限设置 / 视频管理 / 基本配置；")
bullet("档口：拿货标签管理 / 备货单 / 分拣墙管理 / 到货登记 / 退货登记 / 退货签重匹配 / 盲扫分拣发货 / 逐单扫描发货 / 爆款标签发货 / 标签对账 / 到缺货报表 / 档口最早缺货；")
bullet("跨境：备货单管理 / 发货单管理 / 销售统计 / TEMU 利润报表 / 汇率管理 / 首公里组包；")
bullet("对接：新平台对接 / 物流对接 / 单据下载 / 库存同步 / 奇门对接 / API 对接。")

h2("3.3 硬约束与兜底逻辑")
bullet("硬约束：system_prompt 明确『绝对不允许输出「其它」或「其他」』，必须从分类体系中选具体一级；")
bullet("LLM 返回『其它/其他』→ 代码强制纠正为 _guess_category_from_title（标题关键词猜测），并在 reason 标记『[已纠正]』；")
bullet("_guess_category_from_title：命中平台关键词（美团/京东/拼多多/淘宝/天猫/抖音/快手/小红书/微信/苏宁/唯品会/得物/Shopee/TEMU/亚马逊/eBay/平台/对接/API/奇门）→ 对接；否则按 订单/售后/采购/仓储/商品/报表/登录/账款/铺货/档口/配置/分享/跨境/供分销 等关键词映射；都未命中 → 落 配置；")
bullet("API 连续 3 次失败 → 直接返回 category_l1=\"对接\"、confidence=\"low\"（危险默认值，会污染统计与派单）；")
bullet("置信度 confidence（high/medium/low）由 LLM 给出，但代码未对 low 做任何拦截，仍照常写评论+分配处理人。")

h2("3.4 跨模块优先级规则（CROSS_MODULE_RULES）")
bullet("标题出现电商平台名（美团/京东/拼多多/淘宝/天猫/抖音/快手/小红书/微信/苏宁/唯品会/得物/Shopee/TEMU/亚马逊/eBay 等）→ 优先归 对接 > 新平台对接；")
bullet("涉及『对接』数据同步问题（如平台状态不同步）→ 优先归 对接；")
bullet("涉及『配置/策略』：配置端归 配置，使用端归对应业务模块；")
bullet("涉及『报表/数据展示』→ 优先归 报表 对应子类；")
bullet("『追责』/『工单』/『绩效』相关 → 归 仓储 > 工作量登记；")

h2("3.5 当前默认参数")
make_table(
    ["参数", "默认值", "含义"],
    [
        ["story_status_filter", "status_2", "拉取待分类需求的状态过滤"],
        ["deepseek temperature", "0.1", "分类 LLM 采样温度（低，求稳定）"],
        ["max_tokens", "800", "分类 LLM 最大输出 token"],
        ["重试次数", "3", "API 失败重试，全失败兜底为『对接/low』"],
    ],
    widths=[2.2, 1.4, 3.4],
)

doc.add_page_break()

# ===================== 四、PRD 分析 =====================
h1("四、PRD 有效性分析（prd_analyzer）")

h2("4.1 处理流程")
numbered("输入：PrdAnalysisJob.prd_content 与 original_requirement（用户原始需求）。")
numbered("若 prd_content 为空 → 跳过 LLM 调用，标记『待补充 PRD』（避免无效分析）；")
numbered("否则调用 analyze_prd(prd_content, original_requirement) → 写回 completeness_score / coverage_detail / suggestions / status=\"analyzed\"。")
para("注意：original_requirement 若未被正确回填（取不到用户原始需求），模型实际是对『(无原始需求)』打分，覆盖度判断会失真。", italic=True)

h2("4.2 评分维度与权重（默认合计 100）")
make_table(
    ["评分维度", "默认权重", "判分要点"],
    [
        ["需求覆盖度", "30", "PRD 是否覆盖用户需求的所有要点"],
        ["功能详细度", "25", "功能描述是否详细到可开发（功能路径、调整点）"],
        ["交互完整度", "20", "是否描述异常流程、边界条件、数据校验"],
        ["验收标准", "25", "是否有明确、可测试的验收标准"],
    ],
    widths=[1.6, 1.0, 4.4],
)
para("completeness_score = 四个维度得分之和（不超过各维度权重上限）。", bold=True)

h2("4.3 合格判定")
bullet("completeness_score >= prd_pass_threshold（默认 60）→ 合格，无需补充；")
bullet("completeness_score < 60 → 不合格，生成补充建议 suggestions[{category, priority, suggestion}]；")
bullet("category ∈ {功能, 交互, 验收, 数据监控}；priority ∈ {high, medium, low}。")

h2("4.4 三档松紧度评分标准（prompts._PRD_STRICTNESS_CRITERIA 要点）")
h3("需求覆盖度（权重 w_coverage）分档锚点")
bullet("loose：3 以下=未覆盖核心；50%=覆盖部分漏关键点；70%=覆盖核心允许漏次要；90%=覆盖大部分；满分=全覆盖。")
bullet("standard：5 以下=未覆盖核心；40%=覆盖部分漏关键；60%=覆盖核心漏次要；80%=覆盖大部分；满分=全覆盖含边界场景。")
bullet("strict：5 以下；30%=部分漏关键；50%=核心漏边界；70%=大部分含部分边界；90%=全含异常场景；满分=全含异常+数据校验。")
h3("功能详细度（权重 w_functional）分档锚点")
bullet("loose：3 以下=仅方向；50%=有功能点简略；70%=有路径或调整点之一；90%=路径+调整点；满分=路径+调整点（无数据变更不扣）。")
bullet("standard：5 以下；40%=有功能点无路径；60%=有路径无调整点；80%=路径+调整点；满分=路径+调整点+数据变更说明。")
bullet("strict：5 以下；30%=有功能点无路径；50%=有路径无调整点；70%=路径+调整点；90%=路径+调整点+数据变更；满分=路径+调整点+数据变更+影响范围评估。")
h3("交互完整度（权重 w_interaction）分档锚点")
bullet("loose：3 以下=仅正常流程；50%=部分异常；70%=异常或边界之一；满分=异常+边界（不要求权限控制）。")
bullet("standard：5 以下；40%=部分异常；60%=异常+边界；80%=异常+边界+数据校验；满分=异常+边界+数据校验+权限控制。")
bullet("strict：5 以下；30%=部分异常；50%=异常+边界；70%=异常+边界+数据校验；90%=+权限控制；满分=所有异常/边界/数据校验/权限/性能要求。")
h3("验收标准（权重 w_acceptance）分档锚点")
bullet("loose：3 以下=无；50%=简单不可测；70%=可测试；满分=完整（不要求埋点监控）。")
bullet("standard：5 以下；40%=简单不可测；60%=可测试；80%=完整含测试数据；满分=完整+测试数据+埋点监控。")
bullet("strict：5 以下；30%=简单不可测；50%=可测试；70%=完整含测试数据；90%=+埋点监控；满分=完整+测试数据+埋点+回归方案。")

h2("4.5 三档模板检查（prompts._PRD_TEMPLATE_CHECK）")
make_table(
    ["档位", "模板检查要求"],
    [
        ["loose", "仅查核心项（功能描述、验收标准），缺失核心才扣，非核心（场景分析/数据监控）不扣"],
        ["standard", "查标准六项：初步方案/背景、场景分析、功能价值、功能描述（路径+调整点）、验收标准、数据监控/埋点"],
        ["strict", "严格查完整模板，缺失任一项均扣；功能描述须含路径+调整点+数据变更，验收须含测试数据；埋点缺失扣 5 分"],
    ],
    widths=[1.2, 5.8],
)

h2("4.6 注入知识与特殊说明")
bullet("PRD 标准模板：初步方案/背景 → 场景分析 → 功能价值 → 功能描述（路径、调整点）→ 验收标准 → 数据监控/埋点；")
bullet("重要：TAPD API 无法返回图片/设计稿，因此不因为缺图片、截图、设计稿、蓝湖链接而扣分，补充建议中也不得提及『补充图片/设计稿』等；")
bullet("分析仅基于 PRD 文字内容。")

h2("4.7 当前默认参数")
make_table(
    ["参数", "默认值", "含义"],
    [
        ["prd_strictness", "standard", "PRD 评分松紧度 loose/standard/strict"],
        ["prd_pass_threshold", "60", "PRD 合格阈值"],
        ["prd_weight_coverage", "30", "需求覆盖度权重"],
        ["prd_weight_functional", "25", "功能详细度权重"],
        ["prd_weight_interaction", "20", "交互完整度权重"],
        ["prd_weight_acceptance", "25", "验收标准权重"],
    ],
    widths=[2.4, 1.2, 3.4],
)

doc.add_page_break()

# ===================== 五、配置参数总览 =====================
h1("五、配置参数总览（系统默认值）")
make_table(
    ["参数", "默认值", "所属模块", "含义"],
    [
        ["reliability_threshold", "60", "可靠性打分", "可靠性达标阈值"],
        ["question_max_count", "3", "可靠性打分", "补充问题数量上限"],
        ["question_focus", "problem_scenario", "可靠性打分", "补充问题聚焦方向"],
        ["scoring_strictness", "loose", "可靠性打分", "评分松紧度"],
        ["duplicate_history_limit", "500", "重复识别", "对比历史库条数"],
        ["story_status_filter", "status_2", "需求分类", "待分类需求状态过滤"],
        ["prd_strictness", "standard", "PRD 分析", "PRD 评分松紧度"],
        ["prd_pass_threshold", "60", "PRD 分析", "PRD 合格阈值"],
        ["prd_weight_coverage", "30", "PRD 分析", "需求覆盖度权重"],
        ["prd_weight_functional", "25", "PRD 分析", "功能详细度权重"],
        ["prd_weight_interaction", "20", "PRD 分析", "交互完整度权重"],
        ["prd_weight_acceptance", "25", "PRD 分析", "验收标准权重"],
    ],
    widths=[2.3, 1.4, 1.3, 2.0],
)

# ===================== 六、效果现状与改进方向 =====================
h1("六、各模块效果现状与改进方向（摘要）")
para("四大模块当前判断标准已在上文完整梳理。从『效果为何不理想』的角度，可重点改进：", bold=True)
h3("① 可靠性打分")
bullet("默认 loose + 阈值 60 偏松，prompt 反复强调『能理解就给及格』，导致绝大多数需求直接过线、区分度低；")
bullet("纯 LLM 判定、零结构校验：模板占位符未替换等本可确定性检测的问题交给模型凭感觉扣，结果不稳定；")
bullet("改进：调高到 standard、加确定性预检（正则命中模板占位符即预扣固定分），并把补充问题与未达标解耦。")
h3("② 重复需求识别（最该先改）")
bullet("把 500 条历史整段塞进一个 prompt，远超上下文，后段被忽略 → 大量重复漏判；")
bullet("similarity 仅展示、无代码门槛，且 prompt 与代码自相矛盾；")
bullet("改进：引入向量检索/语义相似度预筛，每条只召回 top-20~30 精判；代码层加 similarity 硬门槛 + duplicate_with 精确匹配纠错。")
h3("③ 需求分类")
bullet("『禁止其它』导致模糊需求被关键词猜测硬塞进 对接/配置，误分率高；")
bullet("低置信度不拦截（low 仍照常派单）；API 失败默认落 对接 是危险默认；")
bullet("改进：允许『未分类/待人工』桶，用置信度 gate 拦截 low，API 失败改为待重试/待人工。")
h3("④ PRD 分析")
bullet("original_requirement 常为空，模型对着『(无原始需求)』打分，覆盖度失真；维度分代码层不校验，常对不上；")
bullet("改进：确保原始需求正确回填、空时提示而非硬打；代码层归一则维度分；增加结构化检查清单与 LLM 评分交叉。")

para("")
para("— 文档基于代码静态梳理，默认参数以 config.py / user_settings.py 为准；实际运行以『我的业务配置』内用户覆盖值优先。", italic=True)

doc.save(OUT)
print("SAVED:", OUT)
