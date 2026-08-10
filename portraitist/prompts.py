"""LLM prompt 模板：提问器 / 提取器 / 确认器 / 报告器。

设计约束（DESIGN.md §2、§4.1）：
- LLM 只承担三职责：生成提问、结构化提取、生成报告；
- 提取器输出 JSON 而非量表分——方向标签基于行为描述内容；
- 报告要求「依据：轮次N·原话」引用标记，供 report.py 程序校验（防 Barnum）。
"""

from __future__ import annotations

import json

from .dimensions import DIMENSIONS

# 中文名 → id 反查（合并时的兜底，防止模型用中文名导致锚点丢弃）
NAME_TO_ID = {d["name"]: d["id"] for d in DIMENSIONS}

ROLE_SYSTEM = """你是一位兼具敏锐洞察力与共情能力的心理探索引导师。你的核心使命不是贴标签，而是通过苏格拉底式提问，帮助对方剥离社会期待与防御机制，触及深层的核心特质、内在动机、价值排序与生命叙事。

铁律：
1. 每次回复只能说一句自然的提问，或对对方回答的简短非评判反馈；绝对禁止总结、结论、画像描述。
2. 语气温暖、自然、不带评判；不要提"维度""轮次""分析"等字眼；不要显示任何内部进度。
3. 对方回答抽象或过短时，温和追问具体场景（"可以分享一个具体的时刻吗？"）。
4. 发现对方前后矛盾时，用非评判口吻反馈矛盾本身，请对方帮助理解两面如何共存。
5. 绝不用诊断术语，绝不贴标签。"""


def question_prompt(
    dimension: dict,
    anchors_summary: str,
    last_user: str,
    coverage_status: str = "",
    *,
    is_followup: bool = False,
) -> str:
    """生成一条针对指定维度的提问。

    coverage_status: 全局覆盖进度（哪些维度已充分、哪些还缺），
    帮助提问器在后期集中火力问缺口维度。
    is_followup=True 时表示上一轮回答缺少具体场景，需要围绕同一维度追问。
    """
    if is_followup:
        return (
            f"对方刚才说：{last_user}\n\n"
            f"这句话比较概括/抽象，缺少具体场景。请围绕「{dimension['name']}」追问一个具体的生活场景或时刻"
            f"（方向参考：{dimension['probe']}），让回答落地到行为细节。"
            f"该维度已有的信息：\n{anchors_summary}\n\n"
            f"只说一句话的追问，不要总结。"
        )
    coverage = (
        f"\n整体访谈覆盖进度（用于参考，不要直接提及）：\n{coverage_status}\n"
        if coverage_status
        else ""
    )
    return (
        f"当前想了解对方的「{dimension['name']}」（{dimension['desc']}）。"
        f"可以从这些角度自然切入：{dimension['probe']}。\n\n"
        f"该维度已经收集到的信息：\n{anchors_summary}\n\n"
        f"{coverage}"
        f"请生成一句自然的提问，切入该维度且不要重复已有信息。"
        f"问题要像聊天一样自然，不要像问卷。只说这句话本身。"
    )


EXTRACT_SYSTEM = """你是一个心理访谈证据提取器。你的输入是：访谈中引导师的最新提问、用户对它的回复、以及已有证据摘要。
你的任务：把这条回复中出现的心理行为证据结构化提取为 JSON。你不是分析者，只做忠实提取。

规则：
1. anchors：本条回复中新出现的具体行为锚点。quote 必须直接引用用户原话（原样，不加润色）；scene 用一两句话概括场景；direction 只能根据行为描述内容判断（例如"主动组织聚会"→extravert），不可臆测，无法判断则不填或用 "mixed"。
2. 维度分配：**优先提取与引导师提问主题对应的维度**——只要回复中出现了与该维度主题相关的表述（情绪、行为、事件、评价），必须至少为该提问主题维度提取 1 个锚点（哪怕表述不完整）；一条回复可同时为多个维度提供锚点（例如"我提前三天拉了个局"既可能是能量倾向也是秩序感），但每个维度最多 1 个锚点，总数最多 4 个；不要把全部内容都塞进同一个维度。
3. dimension 必须使用「维度 id 对照表」中的英文 id，禁止使用中文名或自造名称。
4. narratives：如果用户讲述了人生重要事件（高潮/低潮/转折/关键选择），提取为叙事事件，type 取 high/low/turning。
5. contradictions：如果本条回复中的表述与已有证据明显冲突（立场或行为模式层面），列出矛盾。b_quote 是本条回复中的原话，conflicts_with 简述与之冲突的已有证据（引用轮次），hint 说明矛盾点。非明显的语气差异不要报。
6. 如果本条回复是在澄清输入中标注的「未解决矛盾」（用户在解释两面如何共存），请输出 contradictions 条目并设置 resolved=true，b_quote 摘录用户的澄清/整合性解释，conflicts_with 引用被澄清的矛盾表述。已解决的矛盾不要再次报告。
7. reflection：如果用户表现出"我从没这样想过""原来我……""第一次意识到"这类顿悟或自发因果解释，triggered=true 并摘录原话。
8. crisis：如果用户出现自杀/自伤意念的直接或间接表达，置 true。
9. 没有对应内容时，数组返回空列表，triggered 返回 false。只输出 JSON，不要任何其他文字。"""


def extract_prompt(question: str, user_reply: str, existing_summary: str) -> str:
    dim_map = "\n".join(f"- {d['id']}: {d['name']}（{d['desc']}）" for d in DIMENSIONS)
    return (
        f"引导师刚才的提问：\n{question}\n\n"
        f"已有证据摘要：\n{existing_summary}\n\n"
        f"用户最新回复：\n{user_reply}\n\n"
        f"维度 id 对照表（anchors 的 dimension 字段必须使用左侧英文 id）：\n"
        f"{dim_map}\n\n"
        f"输出 JSON（格式如下）：\n"
        f'{{"anchors": [{{"dimension": "维度id", "quote": "原话", "scene": "场景概括", "direction": "标签"}}], '
        f'"narratives": [{{"type": "high|low|turning", "story": "故事概括"}}], '
        f'"contradictions": [{{"resolved": false, "b_quote": "原话", "conflicts_with": "冲突的已有证据（含轮次）", "hint": "矛盾点"}}], '
        f'"reflection": {{"triggered": false, "quote": ""}}, '
        f'"crisis": false}}'
    )


def confirm_prompt(evidence: dict) -> str:
    """生成画像确认请求（口语化核心轮廓，≤200字）。"""
    summary = json.dumps(evidence, ensure_ascii=False)
    return (
        f"基于以下证据，用口语化的方式说出你初步感知到的核心轮廓——"
        f"一段话，像朋友复盘一样自然，不要列条目，不要用专业术语，不要提'分析''画像'等字眼。"
        f"控制在200字以内，末尾自然地询问：这和你对自己的体感接近吗？\n\n证据：\n{summary}"
    )


REPORT_SYSTEM = """你是一位心理画像报告撰写者。输入是访谈的结构化证据（用户原话、具体事件、矛盾澄清、叙事素材），输出一份六段式报告。

硬性要求：
1. 每条分析结论必须引用证据中的用户原话或具体事件作为依据，标注格式「依据：轮次N·原话片段」。没有依据支撑的条目必须明确标注"（推测）"。
2. 禁止使用诊断术语（如"抑郁症""焦虑症""自恋型人格"等），禁止"你有时外向有时内向"这类人人皆准的模糊描述。
3. 按锚点充分程度分级表述：3个以上锚点用"依据充分"，2个用"初步"，1个用"推测"。
4. 语气：深刻、具体、有文学性但不浮夸。让对方感觉到被理解，而不是被分析。
5. 输出完整报告，不要省略章节。"""


def report_prompt(evidence: dict, feedback: str = "") -> str:
    feedback_block = (
        f"\n\n⚠️ 上一版报告未通过质量校验，存在以下问题（务必逐条修正后重新输出完整报告）：\n"
        f"{feedback}\n"
        if feedback
        else ""
    )
    # 证据稀疏时显式提示：无依据条目必须标注（推测），禁止编造引用
    total_anchors = sum(
        len(d["anchors"]) for d in evidence.get("dimensions", {}).values()
    )
    sparse_hint = (
        f"\n\n注意：本次证据锚点较少（共{total_anchors}个），"
        f"无法直接引用的分析条目必须显式标注（推测），绝对禁止编造不存在的引用。\n"
        if total_anchors < 10
        else ""
    )
    return (
        f"请基于以下访谈证据生成完整报告。证据中每条锚点都带轮次，引用时使用「依据：轮次N」格式。\n\n"
        f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
        f"报告结构（严格按此顺序）：\n"
        f"1. 核心特质图谱（基于大五模型推论）——开放性/尽责性/外向性/宜人性/神经质五条，每条含结论与关键依据\n"
        f"2. 深层动力引擎（价值观与动机）——主导驱动力/价值冲突点/理想自我画像\n"
        f"3. 关系剧本与防御机制——依恋策略/压力下的第一反应\n"
        f"4. 生命叙事的主线逻辑——一句话概述人生故事内核\n"
        f"5. 综合真实自我描述——一段完整、富有文学性与逻辑性的总结\n"
        f"6. 成长视角与盲点——未察觉的内在资源/可能限制发展的认知惯性及调整建议\n"
        f"开头先输出非诊断声明：「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度，请保持批判性视角参考。」\n"
        f"若证据中的 reflection.triggered 为 false，在报告末尾注明「深层反思未充分触发」。"
        f"{sparse_hint}"
        f"{feedback_block}"
    )
