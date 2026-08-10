"""报告校验单测：引用检查 / 黑名单 / Barnum 句式 / 结构检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.evidence import new_session
from portraitist.report import check_report

GOOD_REPORT = """「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度，请保持批判性视角参考。」

1. 核心特质图谱
- 开放性：依据充分。依据：轮次2·「我周末会去逛美术馆」。
- 尽责性：初步。依据：轮次3·「我习惯把待办写下来」。

2. 深层动力引擎
- 主导驱动力：自主。依据：轮次4·「我最受不了被人指挥」。

3. 关系剧本与防御机制
- 依恋策略：安全型。依据：轮次5·「我不怕跟伴侣吵架」。

4. 生命叙事的主线逻辑
- 一个不断证明自己价值的逆袭者。依据：轮次6·「高考失利后我复读了一年」。

5. ✨ 综合真实自我描述
- 一段总结。依据：轮次7·「我越来越接受自己了」。

6. 成长视角与盲点
- 内在资源。依据：轮次8·「朋友说我其实很坚韧」。
"""


def session_with_rounds(n=8):
    s = new_session()
    s["rounds"] = n
    s["round_stats"] = [
        {"round": r, "new_anchors": 1, "new_contradictions": 0, "new_narratives": 0, "reflection": False}
        for r in range(1, n + 1)
    ]
    # 满足非稀疏场景（锚点 ≥6）；quotes 与 GOOD_REPORT 引用内容一致（真实性校验）
    s["dimensions"]["trait_energy"]["anchors"] = [
        {"quote": "我周末会去逛美术馆", "round": 2},
        {"quote": "顺便看个展", "round": 2},
        {"quote": "我不怕跟伴侣吵架", "round": 5},
        {"quote": "朋友说我其实很坚韧", "round": 8},
    ]
    s["dimensions"]["trait_order"]["anchors"] = [
        {"quote": "我习惯把待办写下来", "round": 3},
        {"quote": "高考失利后我复读了一年", "round": 6},
    ]
    s["dimensions"]["trait_emotion"]["anchors"] = [
        {"quote": "我最受不了被人指挥", "round": 4},
        {"quote": "我越来越接受自己了", "round": 7},
    ]
    return s


def test_good_report_passes():
    checks = check_report(GOOD_REPORT, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]


def test_empty_report_fails():
    checks = check_report("", session_with_rounds())
    assert checks["ok"] is False


def test_short_report_fails():
    checks = check_report("很短的报告", session_with_rounds())
    assert checks["ok"] is False


def test_missing_section_fails():
    md = GOOD_REPORT.replace("6. 成长视角与盲点", "6. 备注")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("成长视角" in i for i in checks["issues"])


def test_missing_citation_fails():
    md = GOOD_REPORT.replace("依据：轮次8·「朋友说我其实很坚韧」。", "这个人很有韧性。")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("无引用" in i for i in checks["issues"])


def test_speculative_section_without_citation_passes():
    """显式标注（推测）的段落允许无引用——合理降级而非编造。"""
    md = GOOD_REPORT.replace("依据：轮次8·「朋友说我其实很坚韧」。", "这个人可能很有韧性。（推测）")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]


def test_blacklist_diagnosis_fails():
    md = GOOD_REPORT.replace("安全型", "有抑郁症倾向")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("诊断术语" in i for i in checks["issues"])


def test_barnum_pattern_fails():
    md = GOOD_REPORT.replace("安全型。", "你有时外向有时内向。")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("Barnum" in i for i in checks["issues"])


def test_citation_out_of_range_fails():
    md = GOOD_REPORT.replace("依据：轮次8·", "依据：轮次99·")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("越界" in i for i in checks["issues"])


def test_alt_citation_format_accepted():
    md = GOOD_REPORT.replace("依据：轮次2·「我周末会去逛美术馆」。", "〔轮次2〕我周末会去逛美术馆。")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]


def test_chinese_numeral_markdown_headings_accepted():
    """真实模型输出风格：## 一、核心特质图谱 + 【依据：轮次N·…】。"""
    md = GOOD_REPORT
    for num, kw in [(1, "核心特质图谱"), (2, "深层动力引擎"), (3, "关系剧本"),
                    (4, "生命叙事"), (5, "综合真实自我描述"), (6, "成长视角")]:
        cn = "一二三四五六"[num - 1]
        md = md.replace(f"{num}. {kw}", f"## {cn}、{kw}")
    md = md.replace("「", "【").replace("」", "】")
    md = md.replace("「本分析基于对话模型推演", "本分析基于对话模型推演")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]


def test_no_disclaimer_fails():
    md = GOOD_REPORT.replace("「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度，请保持批判性视角参考。」", "")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("非诊断声明" in i for i in checks["issues"])


def test_fabricated_citation_fails():
    """引用轮次无锚点产出 → 疑似编造。"""
    s = session_with_rounds()
    # 轮 3 实际没有锚点产出
    s["round_stats"][2]["new_anchors"] = 0
    md = GOOD_REPORT.replace("依据：轮次3·「我习惯把待办写下来」。", "依据：轮次3·「编造的引用」。")
    checks = check_report(md, s)
    assert checks["ok"] is False
    assert any("疑似编造" in i for i in checks["issues"])


def test_fabricated_quote_content_fails():
    """引用轮次有锚点但内容与原话不符 → 疑似编造（真实性校验）。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("依据：轮次2·「我周末会去逛美术馆」。", "依据：轮次2·「我从来没逛过美术馆」。")
    checks = check_report(md, s)
    assert checks["ok"] is False
    assert any("内容与证据不符" in i for i in checks["issues"])


def test_quote_elision_accepted():
    """节选/润色引用应通过（宽松匹配）。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("「我周末会去逛美术馆」", "「周末会去逛美术馆」")  # 节选
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_mbti_label_blacklisted():
    md = GOOD_REPORT.replace("安全型", "INFP")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("诊断术语" in i or "标签" in i for i in checks["issues"])


def test_absolute_statement_allowed():
    """'你总是X'在有依据时是具体断言，不算 Barnum（引用校验兜底）。"""
    md = GOOD_REPORT.replace("安全型。", "你总是那个率先打破僵局的人。")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]


def test_confidence_labels_missing_warns():
    """第 1 段特质条目缺置信度标注 → warning 不阻塞。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("依据充分。", "。")  # 去掉全部置信度标注
    checks = check_report(md, s)
    assert checks["ok"] is True
    assert any("置信度" in w for w in checks["warnings"])


def test_sparse_evidence_warns():
    """锚点总数过少（<6）→ 引用问题降级为 warning，报告可交付。"""
    s = new_session()
    s["rounds"] = 3
    s["round_stats"] = [
        {"round": r, "new_anchors": 1, "new_contradictions": 0, "new_narratives": 0, "reflection": False}
        for r in (1, 2, 3)
    ]
    s["dimensions"]["trait_energy"]["anchors"] = [{"quote": "x", "round": 1}]
    # 稀疏场景：无引用的段落降级为 warning，ok 仍为 True
    md = GOOD_REPORT.replace("依据：轮次8·「朋友说我其实很坚韧」。", "这个人很有韧性。")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]
    assert any("无引用" in w for w in checks["warnings"])


# ---- _quote_matches 边界（原 ad-hoc 验证沉淀） ----

def test_quote_ellipsis_join_accepted():
    """同轮省略号拼接多个原话片段 → 分段严格匹配通过。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("「我周末会去逛美术馆」", "「我周末会去逛美术馆…顺便看个展」")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_quote_placeholder_prefix_stripped():
    """'原话'/'原话片段'占位符前缀（旧 prompt 泄漏）应被剥离。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("「我周末会去逛美术馆」", "「原话我周末会去逛美术馆」")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_quote_short_fragment_tolerant():
    """短片段（<8字）无法判断 → 宽容通过。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace("「我周末会去逛美术馆」", "「美术馆」")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_quote_cross_round_join_rejected():
    """省略号拼接跨轮内容（该轮无此原话）→ 拦截。"""
    s = session_with_rounds()
    # 轮2锚点是「我周末会去逛美术馆」，「把待办写下来」属于轮3——跨轮拼接应拦
    md = GOOD_REPORT.replace("「我周末会去逛美术馆」", "「我周末会去逛美术馆…把待办写下来」")
    # 但轮2 quotes 不含「把待办写下来」，且轮3 的 quote 也不在轮2——应报内容不符
    checks = check_report(md, s)
    assert checks["ok"] is False
    assert any("内容与证据不符" in i for i in checks["issues"])


def test_section6_substantial_without_citation_warns():
    """第 6 段（成长建议）无引用但内容充分（≥120字）→ warning 不阻塞。"""
    s = session_with_rounds()
    long_tip = "你拥有一种罕见的把人群联结起来的能力。" * 8
    md = GOOD_REPORT.replace(
        "- 内在资源。依据：轮次8·「朋友说我其实很坚韧」。",
        f"- 内在资源。{long_tip}")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_section6_thin_without_citation_rejected():
    """第 6 段无引用且内容单薄 → 拦截（防泛泛建议）。"""
    s = session_with_rounds()
    md = GOOD_REPORT.replace(
        "- 内在资源。依据：轮次8·「朋友说我其实很坚韧」。",
        "- 内在资源。要更开放一些。")
    checks = check_report(md, s)
    assert checks["ok"] is False
    assert any("无引用" in i for i in checks["issues"])


def test_section4_without_narrative_material_warns():
    """第 4 段（生命叙事）无叙事素材时无引用 → warning。"""
    s = session_with_rounds()
    s["narratives"] = []
    md = GOOD_REPORT.replace(
        "- 一个不断证明自己的逆袭者。依据：轮次6·「高考失利后我复读了一年」。",
        "- 一个不断证明自己的逆袭者。")
    checks = check_report(md, s)
    assert checks["ok"] is True, checks["issues"]


def test_somatization_word_allowed():
    """'躯体化'是描述性用词（非诊断名）→ 放行。"""
    md = GOOD_REPORT.replace("安全型", "深刻的躯体化反应")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is True, checks["issues"]
