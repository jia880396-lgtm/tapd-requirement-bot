"""提示词模板

集成旺店通 ERP 专用知识库，提升打分和重复识别的准确度。
"""
import logging
import re

from app.config import settings
from app.user_settings import get_active_setting
from app.knowledge_base import (
    get_reliability_context,
    get_duplicate_context,
    get_prd_context,
    classify_module,
)

logger = logging.getLogger(__name__)


# ---------- 需求可靠性打分 prompt ----------
RELIABILITY_PROMPT = """你是旺店通 ERP 系统的需求评审专家。请对以下用户需求进行可靠性打分。

{knowledge_base}

## 评分原则

整体定位：**标准评分**。综合判断需求的信息完整度、描述清晰度、可实现性和业务价值。
需求截图已由视觉模型识别为文字（【需求截图内容】段）并入描述，按识别文字评估即可；
缺少关键业务信息时应适当扣分。

（本段内容由系统按设置中的「评分松紧度」动态替换：宽松 / 标准 / 严格）

## 确定性预检结果

以下结果由程序直接从输入文本提取，属于评分上限约束；不得忽略或用主观判断抵消：
{quality_precheck}

## 评分方法（必须严格按顺序执行，禁止先打分后找理由）

### 第一步：事实核查

逐项判断以下 6 项事实是否存在，结论只能为"有"或"无"，并摘录原文作为证据。

> **重要：截图识别段享有与正文同等的证据地位。** 当描述中存在「【需求截图内容（AI识别）】」段，
> 该段内的页面标题、模块名、APP/系统名、字段名等均视为已揭示信息，可作为 A~F 各证据项的来源；
> 不要因为"路径只在截图里被识别、不是文字自己写出来的"就判某项为"无"。
>
> 各证据项的判断要点（强制）：
> 【A. 客户标识】是否有具体客户标识（客户账号如 lxm05、客户名称、截图里识别到的租户 ID/店铺名/收件人姓名等）？
>    - 填的是模板文字"客户群名+对接人"或完全为空 → 无
>    - 截图识别到具体收件人/客户昵称（不是"买家昵称为空"这种状态描述）→ 视同 A 已揭示
> 【B. 业务场景】是否说明在哪个业务环节、做什么操作时遇到问题（如"订单审核时批量操作"）？
>    - 填的是模板文字"客户处理…，会…操作"或完全为空 → 无
>    - 截图识别到的页面标题 / 视图名称（如"购买明细""订单审核""手工建单"）即视为业务场景已揭示
> 【C. 问题描述】是否说明遇到的具体问题或错误现象（截图里"买家昵称：空"、具体订单号、报错文字等也算）？
> 【D. 期望效果】是否说明希望系统达到的具体效果？
>    - "希望可以优化""希望更智能"等空话 → 无
> 【E. 定位信息】是否有具体单号、租户账号或明确操作路径？
>    - 文字写"客户管理购买详情订单"或截图识别到"APP / 客户管理 / 购买明细"等页面/菜单组合 → 视为路径已揭示，E 算"有"，value 摘录该路径文字
>    - 只有"APP""ERP""后台"这种泛指，无具体页面/模块名 → 仍判"无"
> 【F. 价值动机】是否说明为什么提这个需求、影响什么客户或业务？
>    - 仅说"客户觉得不是自己的订单""操作繁琐"等具体感受（即使无量化）也算 F 已揭示

### 第二步：按事实组合对档打分

只根据第一步的核查结论，按下表对档打分。分数必须严格落在下方分档的档位值上，不得取中间值，禁止凭感觉调分。各维度 comment 必须引用第一步的核查结论（如"A、B、C 齐全，D 缺失"）。

## 评分维度

1. **信息完整度**（30分）：事实 A~E 的齐全程度
2. **描述清晰度**（30分）：事实 C、D 的具体程度，以及功能点/操作路径是否明确
3. **可实现性**（20分）：事实 C、D 是否明确到可以进入产品评估阶段
4. **业务价值**（20分）：事实 F 是否给出合理的业务动机与影响说明

## 评分标准

### 信息完整度（30分）
- 5分：A、B 均无（模板文字未替换/为空）
- 10分：只有 A 或 B 之一
- 15分：有 A、B，缺 C 或 D
- 20分：A、B、C、D 齐全
- 25分：A~D 齐全且有 E（单号/租户/操作路径）
- 30分：A~E 齐全，含单号和复现步骤

### 描述清晰度（30分）
- 5分：需求模糊（"希望更智能""优化体验"）
- 10分：有方向但无具体功能点
- 15分：有具体功能点但无操作路径
- 20分：有功能点和操作路径（如"订单-订单审核-XX"）
- 25分：有功能路径和调整点
- 30分：描述精确到模块、界面、按钮、操作步骤

### 可实现性（20分）
- 5分：C、D 均无，无法评估
- 10分：有 C 或 D，但范围过大
- 15分：C、D 齐全，范围可控
- 20分：C、D 齐全且有明确的功能路径和调整点

### 业务价值（20分）
- 5分：F 无（价值为空或"无"）
- 10分：有价值描述但无量化
- 15分：有价值且说明省钱/提效
- 20分：有价值、有量化影响（如"影响 X 客户""节省 Y 小时"）

（本段分档由系统按设置中的「评分松紧度」动态替换：宽松 / 标准 / 严格）

## 打分纪律

（本段内容由系统按设置中的「评分松紧度」动态替换）

## 检查要点

（本段内容由系统按设置中的「评分松紧度」动态替换：宽松 / 标准 / 严格）

## 补充问题要求

当需求未达标时，生成补充问题需遵循以下原则：
1. **只问最关键的 2-3 个问题**，不要超过 3 个；如果需求已足够清晰（B/C/D/E 均已揭示），可以只问 1 个甚至不问
2. **只追问真正缺失且对评审有实质帮助的信息**：只有当 evidence 中 present=false、且需求标题、正文与「【需求截图内容（AI识别）】」段都未揭示的信息，才算"真正缺失"——
   - **禁止模板化追问"具体是哪个客户（租户账号或客户名称）"作为通用追问**：仅在 A=无 且截图也无客户名时才问；
     特别地，功能增强类需求（D 描述希望增加/改进某功能）不追问客户标识——功能需求面向所有客户，不需要特定客户才能成立
   - **禁止模板化追问"具体哪个页面/菜单路径"**：仅在 E=无 且标题/截图也无具体页面/模块名时才问
   - **禁止模板化追问"截图发送账单的操作流程"作为通用追问**：仅在 C=无 且截图也无具体错误/字段时才问
3. **只追问问题场景本身**：客户在什么场景下遇到了什么问题
4. **禁止追问技术实现细节**：如"对接方式是API还是……""数据交互方式……"
5. **禁止追问产品方案**：如"涉及哪些平台""具体调整点是什么""验收标准"
6. **禁止追问量化数据**：如"影响多少客户""节省多少时间"
7. **禁止重复问已被截图揭示的信息**：截图已清晰展示页面/字段/错误时，不要再要求提供
8. 问题要简短直接、针对该条需求定制；同一批次需求不要套用完全相同的一组问题
9. **问题必须与该需求的具体内容相关**，不能是放之四海而皆准的通用追问；每个问题都应让提交人看了觉得"确实需要补充这个"

正确示例：
- "请补充具体是哪个客户（租户账号）遇到了这个问题"（仅在 A=无 且截图也无客户名、且是 bug 类需求时）
- "请描述在哪个页面进行什么操作时出现了什么问题"（仅在该需求文字/截图均未揭示页面时）

错误示例（禁止）：
- "请补充具体是哪个客户……" —— 当该需求 OCR 已识别到客户昵称/收件人，或是功能增强类需求时
- "请说明在 APP 中具体哪个页面/菜单路径下查看……" —— 当文字或截图已写出"购买明细"等具体页面时
- "请描述当前界面中买家昵称是否完全不显示，还是部分订单不显示？" —— 截图已展示买家昵称列为空，无需再问
- "请说明对接的具体技术方式"（技术细节）
- "请提供验收标准和调整点"（产品方案）
- "请说明影响多少客户、节省多少时间"（量化数据）

## 输出要求

严格输出以下 JSON（不要输出任何其他内容）：
```json
{{
  "total_score": 0,
  "dimensions": {{
    "completeness": {{"score": 0, "comment": "信息完整度评价，引用 A~E 核查结论"}},
    "clarity": {{"score": 0, "comment": "描述清晰度评价"}},
    "feasibility": {{"score": 0, "comment": "可实现性评价"}},
    "business_value": {{"score": 0, "comment": "业务价值评价"}}
  }},
  "evidence": {{
    "A_customer_id": {{"present": true, "value": "原文证据，无则空字符串"}},
    "B_scenario": {{"present": true, "value": ""}},
    "C_problem": {{"present": true, "value": ""}},
    "D_expected": {{"present": true, "value": ""}},
    "E_location": {{"present": true, "value": ""}},
    "F_value_motive": {{"present": true, "value": ""}}
  }},
  "pass": true,
  "module": "需求所属模块（如订单/售后/商品等）",
  "supplemental_questions": ["补充问题1", "补充问题2"],
  "reason": "一句话总结打分理由，与 evidence 结论一致"
}}
```

字段说明：
- total_score：0-100，必须严格等于各维度 score 之和；系统会按维度分重算总分，两者不一致时以维度分为准，因此请先确定各维度分再相加
- evidence：必须与第一步事实核查结论一致；present 为 true 时 value 摘录原文，为 false 时 value 为空字符串
- 各维度 comment：引用第一步核查结论（如"A、B、C 齐全，D 缺失"），不得写与 evidence 矛盾的评语
- pass：total_score >= 60 时为 true
- module：自动识别的需求所属业务模块
- supplemental_questions：当 pass=false 时必填，2-3 个关键问题，只追问问题场景
- reason：一句话总结打分理由

## 需求内容

标题：{title}
描述：{description}
"""


# 截图识图原则（三种松紧度共用）：有图加分、无图小扣分；无图且文字也缺则直接最低
_SCREENSHOT_PRINCIPLE = (
    "\n\n**截图识图原则**：\n"
    "- **有图加分**：若需求附截图（描述中存在【需求截图内容（AI识别）】段，或图片随请求直入），截图展示了具体业务场景，"
    "可在信息完整度、描述清晰度等维度适当加分（预检已自动提升 cap +2），但截图不能替代具体单号、客户账号等关键文字信息。\n"
    "- **无图小扣分**：若需求完全没有截图（预检中已标记 no_images），信息完整度和描述清晰度各扣 1 分。"
    "截图是加分项而非必须项，无图不应大幅压分。\n"
    "- 若完全没有截图、且 A~F 文字信息也基本缺失（字也不全），则直接给各维度最低分，不做刻意宽松。"
)

# 可靠性打分三种松紧度对应的"评分原则"（抽成常量，供 get_reliability_prompt 与 Skill 渲染共用）
_RELIABILITY_PRINCIPLE = {
    "loose": (
        "整体定位：**宽松评分**。目标是判断需求\"是否足以进入下一步产品评估\"，而非判断需求是否完美。\n"
        "只要需求能让人理解\"谁、在什么场景、遇到了什么问题、希望达到什么效果\"，就应给及格以上分数。\n"
        "需求截图已由视觉模型识别为文字（【需求截图内容（AI识别）】段）并入描述，按识别文字评估即可；\n"
        "不要因为缺少量化数据而过度扣分。"
        + _SCREENSHOT_PRINCIPLE
    ),
    "strict": (
        "整体定位：**严格评分**。需求必须信息完整、描述清晰、有明确业务价值和技术可行性。\n"
        "需求截图已由视觉模型识别为文字（【需求截图内容（AI识别）】段）并入描述，按识别文字评估即可；\n"
        "缺少具体单号、量化数据等关键定位信息时应适当扣分。"
        + _SCREENSHOT_PRINCIPLE
    ),
    "standard": (
        "整体定位：**标准评分**。综合判断需求的信息完整度、描述清晰度、可实现性和业务价值。\n"
        "需求截图已由视觉模型识别为文字（【需求截图内容（AI识别）】段）并入描述，按识别文字评估即可；\n"
        "缺少关键业务信息时应适当扣分。"
        + _SCREENSHOT_PRINCIPLE
    ),
}
_PRINCIPLE_MAP = _RELIABILITY_PRINCIPLE


# 可靠性打分三种松紧度对应的"评分标准"分档。
# 档位以第一步事实核查的 A~F 组合定义（模型先打勾再对档，不做程度判断）。
_RELIABILITY_CRITERIA = {
    "loose": """### 信息完整度（30分）
- 5分：A、B 均无（模板文字未替换/为空）
- 15分：只有 A 或 B 之一，C 缺失或过于简略
- 22分：A、B、C 齐全（能理解谁在什么场景遇到什么问题）
- 28分：A~D 齐全且有 E（单号/租户/操作路径）
- 30分：A~E 全部齐全且具体

### 描述清晰度（30分）
- 5分：需求极其模糊（"希望更智能""优化体验"）
- 15分：有明确方向，能大致理解诉求
- 22分：C 成立，问题清楚，能理解在哪个环节遇到了什么困难
- 28分：C、D 齐全，有具体功能点或操作环节
- 30分：问题描述精确，功能点和操作环节都明确（具体到模块/界面）

### 可实现性（20分）
- 5分：C、D 均无，无法理解要做什么
- 12分：有 C 或 D，方向明确，范围较大但可进入产品评估
- 16分：C、D 齐全，范围可控，可进入产品评估
- 20分：C、D 齐全且有具体调整点/功能点

### 业务价值（20分）
- 5分：F 无，完全看不出为什么要提这个需求
- 12分：有合理动机（解决某类客户问题/优化流程）
- 16分：动机明确，能看出对客户或业务有帮助
- 20分：动机明确，有量化或具体客户影响""",
    "standard": """### 信息完整度（30分）
- 5分：A、B 均无（模板文字未替换/为空）
- 10分：只有 A 或 B 之一
- 15分：有 A、B，缺 C 或 D
- 20分：A、B、C、D 齐全
- 25分：A~D 齐全且有 E（单号/租户/操作路径）
- 30分：A~E 齐全，含单号和复现步骤

### 描述清晰度（30分）
- 5分：需求模糊（"希望更智能""优化体验"）
- 10分：有方向但无具体功能点
- 15分：有具体功能点但无操作路径
- 20分：有功能点和操作路径（如"订单-订单审核-XX"）
- 25分：有功能路径和调整点
- 30分：描述精确到模块、界面、按钮、操作步骤

### 可实现性（20分）
- 5分：C、D 均无，无法评估
- 10分：有 C 或 D，但范围过大
- 15分：C、D 齐全，范围可控
- 20分：C、D 齐全且有明确的功能路径和调整点

### 业务价值（20分）
- 5分：F 无（价值为空或"无"）
- 10分：有价值描述但无量化
- 15分：有价值且说明省钱/提效
- 20分：有价值、有量化影响（如"影响 X 客户""节省 Y 小时"）""",
    "strict": """### 信息完整度（30分）
- 5分：A、B 均无（模板文字未替换/为空）
- 10分：只有 A 或 B 之一
- 15分：有 A、B，缺 C 或 D
- 20分：A~D 齐全但无 E
- 25分：A~E 齐全（有单号或租户）
- 30分：A~E 齐全，含单号、复现步骤、影响范围

### 描述清晰度（30分）
- 5分：需求模糊（"希望更智能""优化体验"）
- 10分：有方向但无具体功能点
- 15分：有具体功能点但无操作路径
- 20分：有功能点和操作路径（如"订单-订单审核-XX"）
- 25分：有功能路径和调整点，能区分现状与期望
- 30分：描述精确到模块、界面、按钮、操作步骤和期望结果

### 可实现性（20分）
- 5分：C、D 均无，无法评估
- 10分：有 C 或 D，范围过大
- 15分：C、D 齐全，范围可控
- 20分：C、D 齐全，有功能路径和调整点，技术方案可判断

### 业务价值（20分）
- 5分：F 无（价值为空或"无"）
- 10分：有价值描述但无量化
- 15分：有价值且说明省钱/提效
- 20分：有价值、有量化影响或明确的客户影响范围""",
}


# 可靠性打分纪律（三种松紧度，与评分标准联动替换）
_SCORE_DISCIPLINE = {
    "loose": (
        "以下规则约束打分上限，不得忽略：\n"
        "- 信息完整度不得给 ≥25 分，除非证据 A~E 中至少 4 项为'有'\n"
        "- 描述清晰度不得给 ≥25 分，除非证据中提及了具体功能点或操作路径\n"
        "- **无截图**的需求：信息完整度和描述清晰度各扣 1 分（图片是加分项，不应大幅压分）\n""- **有截图**的需求：信息完整度和描述清晰度 cap 各+2（截图提供可视化证据）\n"
        "- 业务价值不得给满分（20），除非有量化数据（数字+单位）\n"
        "- 禁止因需求格式工整而给予同情分，必须严格按证据对档"
    ),
    "standard": (
        "以下规则约束打分上限，不得忽略：\n"
        "- 信息完整度不得给 ≥25 分，除非 evidence 中 A 有具体客户账号且 E 有具体单号\n"
        "- 描述清晰度不得给 ≥25 分，除非 evidence C 中有具体功能路径（模块-界面-功能）\n"
        "- **无截图**的需求：信息完整度和描述清晰度各扣 1 分（图片是加分项，不应大幅压分）\n""- **有截图**的需求：信息完整度和描述清晰度 cap 各+2（截图提供可视化证据）\n"
        "- 业务价值不得给 ≥15 分，除非 evidence F 有量化数据或明确客户影响范围\n"
        "- 可实现性不得给满分（20），除非同时有功能路径和明确调整点\n"
        "- 禁止因需求格式工整而给予同情分，必须严格按第一步证据对档"
    ),
    "strict": (
        "以下规则约束打分上限，不得忽略：\n"
        "- 信息完整度不得给 ≥20 分，除非 evidence 中同时有客户账号、具体单号和复现步骤\n"
        "- 描述清晰度不得给 ≥20 分，除非 evidence 中有具体功能路径（模块-界面-功能-按钮）\n"
        "- 业务价值不得给 ≥15 分，除非有量化影响数据（影响 N 客户/节省 N 小时）\n"
        "- 可实现性不得给 ≥15 分，除非有功能路径+调整点+验收标准\n"
        "- 禁止因需求格式工整而给予同情分，必须严格按第一步证据对档"
    ),
}

# 可靠性打分三种松紧度对应的"检查要点"（与评分原则口径一致，渲染时联动替换）
_RELIABILITY_CHECKS = {
    "loose": """仅检查以下关键问题（存在则适当扣分，不要过度扣分）：
- 【客户信息】填的是模板文字"客户群名+对接人"而非实际客户标识
- 【业务场景】填的是模板文字"客户处理…，会…操作"而非实际场景
- 【希望实现的效果】过于模糊，如"希望可以优化"
- 需求完全无法理解要做什么

**注意**：截图已由视觉模型识别为文字（【需求截图内容】段）并入描述，按识别文字评估即可；不要因为没有量化数据、没有技术方案而扣分。\n\n**截图补充原则**：若需求已附截图或描述中存在【需求截图内容（AI识别）】段，不要要求提交人"补充截图/提供设计稿"——截图已体现场景；仅当完全无图且无任何场景信息时，才提示补充截图。""",
    "standard": """检查以下问题（存在则按分档扣分）：
- 【客户信息】填的是模板文字"客户群名+对接人"而非实际客户标识
- 【业务场景】填的是模板文字"客户处理…，会…操作"而非实际场景
- 【遇到的问题】缺少具体单号、租户或操作路径，难以定位问题
- 【希望实现的效果】过于模糊，如"希望可以优化"
- 【需求价值】为空或仅写"无"
- 需求完全无法理解要做什么

**注意**：截图已由视觉模型识别为文字（【需求截图内容】段）并入描述，按识别文字评估即可；不要因为没有技术方案而扣分。\n\n**截图补充原则**：若需求已附截图或描述中存在【需求截图内容（AI识别）】段，不要要求提交人"补充截图/提供设计稿"——截图已体现场景；仅当完全无图且无任何场景信息时，才提示补充截图。""",
    "strict": """严格检查以下问题（存在则按分档扣分，缺失项越多扣分越重）：
- 【客户信息】填的是模板文字"客户群名+对接人"而非实际客户标识
- 【业务场景】填的是模板文字"客户处理…，会…操作"而非实际场景
- 【遇到的问题】缺少具体单号、租户或复现步骤
- 【希望实现的效果】过于模糊，如"希望可以优化"
- 【需求价值】为空，或未说明影响范围/客户数量
- 需求完全无法理解要做什么

**注意**：严格档要求关键信息齐备，缺少具体单号、量化数据等关键信息时适当扣分。\n\n**截图补充原则**：若需求已附截图或描述中存在【需求截图内容（AI识别）】段，不要要求提交人"补充截图/提供设计稿"——截图已体现场景；仅当完全无图且无任何场景信息时，才提示补充截图。""",
}


# ---------- 重复需求识别 prompt ----------
DUPLICATE_DETECTION_PROMPT = """你是旺店通 ERP 系统的需求重复性识别专家。请判断以下需求是否与历史需求重复。

{knowledge_base}

## 判定标准

### 重复（is_duplicate=true）
- 核心功能诉求一致，仅客户信息不同
- 平台+模块+操作三要素相同
- 同一功能点的不同表述（如"货品页面布局优化" vs "商品页面UI调整"）

### 相似不重复（is_duplicate=false, similarity > 0.5）
- 相关但解决不同问题
- 同模块但不同功能点

### 不重复（is_duplicate=false, similarity < 0.5）
- 完全不同的需求

## 识别技巧

1. **忽略客户信息**：不同客户提交的同类需求算重复（核心诉求一致即可）
2. **关注功能点**：比较核心功能诉求，而非表述方式
3. **模块归类**：先判断需求所属模块，同模块内重点比较
4. **操作类型**：新增/优化/修复 是不同的操作类型，但同操作类型+同功能点算重复

## 输出要求

严格输出以下 JSON（不要输出任何其他内容）：
```json
{{
  "is_duplicate": false,
  "duplicate_with": ["需求ID1", "需求ID2"],
  "similarity": 0.0,
  "duplicate_type": "重复类型（同一客户重复提交/不同客户同类需求/已有功能重复/同类优化不同表述）",
  "reason": "判定依据，说明为什么重复或不重复"
}}
```

字段说明：
- is_duplicate：是否重复（similarity >= 0.8 时为 true）
- duplicate_with：重复的需求 ID 列表（不重复时为空数组）
- similarity：相似度 0.0-1.0
- duplicate_type：重复类型分类
- reason：判定依据说明

## 待判断需求

{current_requirement}

## 历史需求库（最近 N 条）

{historical_requirements}
"""


# ---------- PRD 分析 prompt ----------
# 模板：维度权重和评分标准通过 get_prd_prompt 动态注入
PRD_ANALYSIS_PROMPT = """你是旺店通 ERP 系统的 PRD 评审专家。请对比用户原始需求和产品经理填写的 PRD，给出完整度打分和补充建议。

{knowledge_base}

## 评分原则

{strictness_principle}

**图片说明**：TAPD 内嵌截图已通过视觉模型识别为文字，可能以「【需求截图内容（AI识别）】」段出现在需求文字中，评分时视为有效需求信息；
- 蓝湖链接/外部设计稿无法获取内容，不在检查范围内
- 若需求文字中没有截图内容，不要因缺少截图而扣分
- 补充建议中不要提及"补充图片""提供设计稿"等无法获取的内容

## 评分维度

1. **需求覆盖度**（{w_coverage}分）：PRD 是否覆盖了用户需求的所有要点
2. **功能详细度**（{w_functional}分）：功能描述是否详细到可开发（有功能路径、调整点）
3. **交互完整度**（{w_interaction}分）：是否描述了异常流程、边界条件、数据校验
4. **验收标准**（{w_acceptance}分）：是否有明确的验收标准（可测试的断言）

## 评分标准

{scoring_criteria}

## PRD 模板检查

{template_check}

## 合格判定

- completeness_score >= {pass_threshold} 视为合格，无需补充
- completeness_score < {pass_threshold} 视为不合格，需生成补充建议

## 输出要求

严格输出以下 JSON（不要输出任何其他内容）：
```json
{{
  "completeness_score": 0,
  "coverage": {{
    "covered_points": ["已覆盖点1", "已覆盖点2"],
    "missing_points": ["遗漏点1", "遗漏点2"]
  }},
  "dimensions": {{
    "requirement_coverage": 0,
    "functional_detail": 0,
    "interaction_completeness": 0,
    "acceptance_criteria": 0
  }},
  "suggestions": [
    {{"category": "功能", "priority": "high", "suggestion": "具体建议"}}
  ],
  "reason": "一句话总结"
}}
```

字段说明：
- completeness_score：0-100，等于各维度分数之和（不超过各维度权重上限）
- dimensions.requirement_coverage：0-{w_coverage}
- dimensions.functional_detail：0-{w_functional}
- dimensions.interaction_completeness：0-{w_interaction}
- dimensions.acceptance_criteria：0-{w_acceptance}
- coverage.covered_points：PRD 已覆盖的需求点
- coverage.missing_points：PRD 遗漏的需求点
- suggestions：补充建议清单，category ∈ {{功能, 交互, 验收, 数据监控}}, priority ∈ {{high, medium, low}}

## 用户原始需求

{original_requirement}

## 确定性结构化预检

以下事实由程序直接从 PRD 文字中检查得出。请逐项核对，不能因语言流畅而忽略缺失项：
{quality_precheck}

## PRD 内容

{prd_content}
"""


# PRD 评分松紧度对应的原则说明
_PRD_STRICTNESS_PRINCIPLE = {
    "loose": (
        "整体定位：**宽松评分**。目标是判断 PRD 是否足以进入开发评估，而非追求完美。\n"
        "只要 PRD 能让开发理解\"要做什么、为谁做、解决什么问题\"，就应给及格以上分数。\n"
        "不因缺少埋点监控而扣分；模板结构缺失不严重时不扣分。"
    ),
    "standard": (
        "整体定位：**标准评分**。综合判断 PRD 的覆盖度、详细度和可测试性。\n"
        "核心诉求必须覆盖，功能描述需有路径，验收标准需可测试。\n"
        "缺少埋点监控等非核心项时适当扣分但不严重扣分。"
    ),
    "strict": (
        "整体定位：**严格评分**。PRD 必须结构完整、信息详尽、可测试可验证。\n"
        "必须包含背景、场景分析、功能价值、功能描述、验收标准、埋点监控等完整模板结构，缺失任一项均扣分。\n"
        "验收标准必须有测试数据；功能描述必须有功能路径、调整点和数据变更说明。"
    ),
}


# PRD 评分松紧度对应的评分标准（各维度分档描述）
_PRD_STRICTNESS_CRITERIA = {
    "loose": """### 需求覆盖度（{w_coverage}分）
- 3分以下：PRD 完全未覆盖用户核心诉求
- 50%分：覆盖部分诉求，遗漏关键点
- 70%分：覆盖核心诉求，允许遗漏次要点
- 90%分：覆盖大部分诉求
- 满分：覆盖所有核心诉求

### 功能详细度（{w_functional}分）
- 3分以下：仅有方向，无具体功能描述
- 50%分：有功能点但描述简略
- 70%分：有功能路径或调整点之一
- 90%分：有功能路径和调整点
- 满分：有功能路径、调整点（无数据变更说明不扣分）

### 交互完整度（{w_interaction}分）
- 3分以下：仅描述正常流程
- 50%分：描述了部分异常流程
- 70%分：描述了异常流程或边界条件之一
- 满分：描述了异常流程和边界条件（不要求权限控制）

### 验收标准（{w_acceptance}分）
- 3分以下：无验收标准
- 50%分：有简单验收标准但不可测试
- 70%分：有可测试的验收标准
- 满分：有完整的验收标准（不要求埋点监控）""",
    "standard": """### 需求覆盖度（{w_coverage}分）
- 5分以下：PRD 未覆盖用户核心诉求
- 40%分：覆盖部分诉求，遗漏关键点
- 60%分：覆盖核心诉求，遗漏次要点
- 80%分：覆盖大部分诉求
- 满分：覆盖所有诉求，含边界场景

### 功能详细度（{w_functional}分）
- 5分以下：仅有方向，无具体功能描述
- 40%分：有功能点但无功能路径
- 60%分：有功能路径（模块--界面--功能）但无调整点
- 80%分：有功能路径和调整点
- 满分：有功能路径、调整点、数据变更说明

### 交互完整度（{w_interaction}分）
- 5分以下：仅描述正常流程
- 40%分：描述了部分异常流程
- 60%分：描述了异常流程和边界条件
- 80%分：描述了异常流程、边界条件、数据校验
- 满分：描述了异常流程、边界条件、数据校验、权限控制

### 验收标准（{w_acceptance}分）
- 5分以下：无验收标准
- 40%分：有简单验收标准但不可测试
- 60%分：有可测试的验收标准
- 80%分：有完整的验收标准，含测试数据
- 满分：有完整的验收标准、测试数据、埋点监控""",
    "strict": """### 需求覆盖度（{w_coverage}分）
- 5分以下：PRD 未覆盖用户核心诉求
- 30%分：覆盖部分诉求，遗漏关键点
- 50%分：覆盖核心诉求，但遗漏边界场景
- 70%分：覆盖大部分诉求，含部分边界场景
- 90%分：覆盖所有诉求，含异常场景
- 满分：覆盖所有诉求，含异常场景和数据校验

### 功能详细度（{w_functional}分）
- 5分以下：仅有方向，无具体功能描述
- 30%分：有功能点但无功能路径
- 50%分：有功能路径但无调整点
- 70%分：有功能路径和调整点
- 90%分：有功能路径、调整点、数据变更说明
- 满分：有完整功能路径、调整点、数据变更说明、影响范围评估

### 交互完整度（{w_interaction}分）
- 5分以下：仅描述正常流程
- 30%分：描述了部分异常流程
- 50%分：描述了异常流程和边界条件
- 70%分：描述了异常流程、边界条件、数据校验
- 90%分：描述了异常流程、边界条件、数据校验、权限控制
- 满分：描述了所有异常场景、边界条件、数据校验、权限控制、性能要求

### 验收标准（{w_acceptance}分）
- 5分以下：无验收标准
- 30%分：有简单验收标准但不可测试
- 50%分：有可测试的验收标准
- 70%分：有完整的验收标准，含测试数据
- 90%分：有完整的验收标准、测试数据、埋点监控
- 满分：有完整的验收标准、测试数据、埋点监控、回归测试方案""",
}


# PRD 模板检查要求（按松紧度区分）
_PRD_TEMPLATE_CHECK = {
    "loose": (
        "检查 PRD 是否包含核心结构（缺失核心项才扣分，非核心项不扣分）：\n"
        "- 功能描述（核心）\n"
        "- 验收标准（核心）\n"
        "注：场景分析、数据监控等非核心项缺失不扣分。"
    ),
    "standard": (
        "检查 PRD 是否包含以下标准结构（缺失则扣分）：\n"
        "- 初步方案/背景\n"
        "- 场景分析\n"
        "- 功能价值\n"
        "- 功能描述（功能路径、调整点）\n"
        "- 验收标准\n"
        "- 数据监控/埋点"
    ),
    "strict": (
        "严格检查 PRD 是否包含完整模板结构（缺失任一项均扣分）：\n"
        "- 初步方案/背景（必须）\n"
        "- 场景分析（必须）\n"
        "- 功能价值（必须）\n"
        "- 功能描述：功能路径、调整点、数据变更说明（必须完整）\n"
        "- 验收标准：含测试数据（必须）\n"
        "- 数据监控/埋点（必须，缺失扣 5 分）"
    ),
}


# ---------- 评论写回模板 ----------
RELIABILITY_COMMENT_TEMPLATE = """【需求初步评估】

您好！该需求已完成初步评估，得分 {score} 分（满分 100）。

{reason}
{questions_block}{extra_tip}
感谢您的配合！

---
（本评论由需求处理机器人自动生成）
"""

DUPLICATE_COMMENT_TEMPLATE = """【重复需求提醒】

检测到本需求与以下历史需求存在重复：
{duplicate_list}

相似度：{similarity}
重复类型：{duplicate_type}
判定依据：{reason}

请确认是否需要合并或调整。
"""

PRD_SUGGESTION_COMMENT_TEMPLATE = """【PRD 完整度评估结果】

完整度：{score}/100

## 覆盖情况
✓ 已覆盖：
{covered}

✗ 遗漏：
{missing}

## 补充建议
{suggestions}

---
（本评论由需求处理机器人自动生成）
"""


# ---------- 渲染函数：注入知识库 ----------
def _append_fewshot(prompt: str, skill, k: int = 3) -> str:
    """若 Skill 存在且案例库有 is_mismatch 样本，把 few-shot 块追加到 prompt 末尾。

    行为不变保证：skill 缺失 / 无 skill_id / 案例库为空 / 构建失败 时都原样返回 prompt，
    绝不破坏线上推理。few-shot 仅作学习样例，与上方当前需求判定隔离。
    """
    if not skill or not skill.get("skill_id"):
        return prompt
    try:
        from app.skill_store import build_fewshot_examples
        fs = build_fewshot_examples(skill["skill_id"], k=k)
        if fs:
            return prompt + _FEWSHOT_HEADER + fs
    except Exception as e:
        logger.warning(f"[prompts] few-shot 注入失败，已跳过：{e}")
    return prompt


_FEWSHOT_HEADER = "\n\n## 评分校准样例（few-shot，仅作学习参考，不影响上方当前需求的判定）\n以下正面/反面示例用于校准评分尺度，请据此判断当前需求的描述质量档位。\n\n"


def _replace_section(prompt: str, header: str, content: str) -> str:
    """精确替换 prompt 中「## header」段的内容，只替换到下一段标题之前，不吞后续段落。

    与段落顺序无关：匹配标题行（允许标题带括号后缀，如旧模板的
    "## 评分标准（宽松标准，能让人理解即可）"）到下一个 "## " 标题或文末。
    若 prompt 中不存在该段（用户编辑过 Skill 模板），原样返回。
    """
    pattern = re.compile(rf'(## {re.escape(header)}[^\n]*\n\n).*?(?=\n\n## |\Z)', re.DOTALL)
    return pattern.sub(lambda m: m.group(1) + content, prompt, count=1)


def _resolve_percent_scores(criteria_text: str, weights: dict[str, float]) -> str:
    """把 PRD 分档文本中的百分比档位（如"50%分"）换算为具体分数（如"15分"）。

    依据各维度当前权重换算，避免模型自行心算百分比产生非整数分或锚点漂移。
    维度归属由所在 "### 维度名（X分）" 小节标题决定。
    """
    dim_map = {
        "需求覆盖度": "coverage",
        "功能详细度": "functional",
        "交互完整度": "interaction",
        "验收标准": "acceptance",
    }
    current_dim = None
    lines = []
    for line in criteria_text.split("\n"):
        m = re.match(r"### (.+?)（.+?分）", line)
        if m:
            current_dim = dim_map.get(m.group(1))
        if current_dim:
            try:
                weight = float(weights.get(current_dim, 0))
            except (TypeError, ValueError):
                weight = 0.0
            line = re.sub(
                r"(\d+)%分",
                lambda mm: f"{int(round(weight * int(mm.group(1)) / 100))}分",
                line,
            )
        lines.append(line)
    return "\n".join(lines)


def _resolve_reliability_skill(skill):
    """延迟拉取模块 Skill（避免循环导入）；已传入则直接返回。"""
    if skill is not None:
        return skill
    try:
        from app.skill_store import get_active_skill
        return get_active_skill("reliability")
    except Exception:
        return None


def get_reliability_prompt(title: str, description: str, quality_precheck: str = "无确定性缺陷", skill=None) -> str:
    """生成可靠性打分 prompt（注入知识库、用户配置与确定性预检结果）。

    优先使用 module Skill（若存在）：以 Skill 的 prompt_text 为基准模板，用 Skill 的
    params 替换阈值/松紧度/问题数，kb_context 为空时回退标准知识库。Skill 缺失时
    完全回退到原硬编码逻辑，保证行为不变。
    """
    # 兜底参数（无 Skill 或 Skill 缺字段时使用系统/用户配置）
    threshold = get_active_setting("reliability_threshold")
    qmax = get_active_setting("question_max_count")
    focus = get_active_setting("question_focus")
    strictness = get_active_setting("scoring_strictness")

    skill = _resolve_reliability_skill(skill)
    if skill and skill.get("prompt_text"):
        base = skill["prompt_text"]
        params = skill.get("params") or {}
        threshold = params.get("reliability_threshold", threshold)
        qmax = params.get("question_max_count", qmax)
        focus = params.get("question_focus", focus)
        strictness = params.get("scoring_strictness", strictness)
        kb = skill.get("kb_context") or get_reliability_context()
    else:
        base = RELIABILITY_PROMPT
        kb = get_reliability_context()

    # 松紧度：原则 / 分档 / 检查要点三段联动，非法值回退标准档
    if strictness not in _PRINCIPLE_MAP:
        strictness = "standard"
    principle = _PRINCIPLE_MAP[strictness]
    criteria = _RELIABILITY_CRITERIA.get(strictness, _RELIABILITY_CRITERIA["standard"])
    checks = _RELIABILITY_CHECKS.get(strictness, _RELIABILITY_CHECKS["standard"])

    # 补充问题聚焦方向
    focus_map = {
        "problem_scenario": "只追问问题场景本身：客户在什么场景下遇到了什么问题",
        "all": "可追问问题场景、技术实现、产品方案等各方面",
    }
    focus_text = focus_map.get(focus, focus_map["problem_scenario"])

    # 替换原 prompt 中的评分原则 / 评分标准 / 检查要点（精确锚定到段尾，不吞后续段落）
    prompt = base
    prompt = _replace_section(prompt, "评分原则", principle)
    prompt = _replace_section(prompt, "评分标准", criteria)
    discipline = _SCORE_DISCIPLINE.get(strictness, _SCORE_DISCIPLINE["standard"])
    prompt = _replace_section(prompt, "打分纪律", discipline)
    prompt = _replace_section(prompt, "检查要点", checks)
    # 替换补充问题数量
    prompt = prompt.replace("**只问最关键的 2-3 个问题**，不要超过 3 个",
                            f"**只问最关键的 {qmax} 个问题**，不要超过 {qmax} 个")
    # 替换聚焦方向
    prompt = prompt.replace("**只追问问题场景本身**：客户在什么场景下遇到了什么问题",
                            f"**{focus_text}**")
    # 替换及格线
    prompt = prompt.replace("total_score >= 60 时为 true",
                            f"total_score >= {threshold} 时为 true")

    rendered = prompt.format(
        knowledge_base=kb,
        title=title,
        description=description or "(无描述)",
        quality_precheck=quality_precheck,
    )
    return _append_fewshot(rendered, skill)


def _resolve_duplicate_skill(skill):
    if skill is not None:
        return skill
    try:
        from app.skill_store import get_active_skill
        return get_active_skill("duplicate")
    except Exception:
        return None


def get_duplicate_prompt(
    title: str,
    description: str,
    historical_requirements: str,
    skill=None,
) -> str:
    """生成重复识别 prompt（注入知识库）。

    若 Skill 存在，用其 prompt_text 为基准并替换相似度阈值占位符；否则回退硬编码模板。
    """
    skill = _resolve_duplicate_skill(skill)
    similarity_threshold = 0.8
    kb = None
    if skill and skill.get("prompt_text"):
        base = skill["prompt_text"]
        params = skill.get("params") or {}
        similarity_threshold = params.get("similarity_threshold", 0.8)
        kb = skill.get("kb_context") or get_duplicate_context()
    else:
        base = DUPLICATE_DETECTION_PROMPT
        kb = get_duplicate_context()

    prompt = base.replace("similarity >= 0.8 时为 true", f"similarity >= {similarity_threshold} 时为 true")
    current = f"标题：{title}\n描述：{description or '(无描述)'}"
    rendered = prompt.format(
        knowledge_base=kb,
        current_requirement=current,
        historical_requirements=historical_requirements or "(暂无历史需求)",
    )
    return _append_fewshot(rendered, skill)


def _resolve_prd_skill(skill):
    if skill is not None:
        return skill
    try:
        from app.skill_store import get_active_skill
        return get_active_skill("prd")
    except Exception:
        return None


def get_prd_prompt(prd_content: str, original_requirement: str, quality_precheck: str = "无", skill=None) -> str:
    """生成 PRD 分析 prompt（注入知识库、评分配置与确定性结构预检）。

    若 Skill 存在，用其 prompt_text 为基准，params 覆盖松紧度/权重/及格线；否则回退硬编码。
    """
    # 兜底参数
    strictness = get_active_setting("prd_strictness") or "standard"
    w_coverage = get_active_setting("prd_weight_coverage")
    w_functional = get_active_setting("prd_weight_functional")
    w_interaction = get_active_setting("prd_weight_interaction")
    w_acceptance = get_active_setting("prd_weight_acceptance")
    pass_threshold = get_active_setting("prd_pass_threshold")

    skill = _resolve_prd_skill(skill)
    if skill and skill.get("prompt_text"):
        # 以 Skill 的 prompt_text 为基准模板（与其他三个模块对齐），
        # params 覆盖松紧度/权重/及格线；kb_context 为空时回退标准知识库。
        base = skill["prompt_text"]
        params = skill.get("params") or {}
        strictness = params.get("prd_strictness", strictness) or "standard"
        w_coverage = params.get("prd_weight_coverage", w_coverage)
        w_functional = params.get("prd_weight_functional", w_functional)
        w_interaction = params.get("prd_weight_interaction", w_interaction)
        w_acceptance = params.get("prd_weight_acceptance", w_acceptance)
        pass_threshold = params.get("prd_pass_threshold", pass_threshold)
        kb = skill.get("kb_context") or get_prd_context()
    else:
        base = PRD_ANALYSIS_PROMPT
        kb = get_prd_context()

    # 兜底非法值
    if strictness not in _PRD_STRICTNESS_PRINCIPLE:
        strictness = "standard"

    # 评分标准模板里有 {w_xxx} 占位符，先替换为实际权重
    scoring_criteria = _PRD_STRICTNESS_CRITERIA[strictness].format(
        w_coverage=w_coverage,
        w_functional=w_functional,
        w_interaction=w_interaction,
        w_acceptance=w_acceptance,
    )
    # 把百分比档位（如"50%分"）换算为具体分数（如"15分"），
    # 消除模型自行心算百分比带来的非整数分与锚点漂移。
    scoring_criteria = _resolve_percent_scores(scoring_criteria, {
        "coverage": w_coverage,
        "functional": w_functional,
        "interaction": w_interaction,
        "acceptance": w_acceptance,
    })

    rendered = base.format(
        knowledge_base=kb,
        strictness_principle=_PRD_STRICTNESS_PRINCIPLE[strictness],
        scoring_criteria=scoring_criteria,
        template_check=_PRD_TEMPLATE_CHECK[strictness],
        w_coverage=w_coverage,
        w_functional=w_functional,
        w_interaction=w_interaction,
        w_acceptance=w_acceptance,
        pass_threshold=pass_threshold,
        original_requirement=original_requirement or "(无原始需求)",
        prd_content=prd_content or "(PRD 为空)",
        quality_precheck=quality_precheck,
    )
    return _append_fewshot(rendered, skill)
