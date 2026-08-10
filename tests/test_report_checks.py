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


def test_no_disclaimer_fails():
    md = GOOD_REPORT.replace("「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度，请保持批判性视角参考。」", "")
    checks = check_report(md, session_with_rounds())
    assert checks["ok"] is False
    assert any("非诊断声明" in i for i in checks["issues"])
