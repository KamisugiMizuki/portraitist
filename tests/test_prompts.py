"""确认/提问 prompt 新行为测试：深度洞察要求 + 修正反馈传递 + 提问衔接要求。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.prompts import confirm_prompt, question_prompt
from portraitist.dimensions import DIMENSIONS


def test_confirm_prompt_demands_insight():
    """确认 prompt 必须要求模式识别/假设性解释，而不是复述。"""
    p = confirm_prompt({"dimensions": {}, "rounds": 3})
    assert "不要复述" in p
    assert "张力点" in p
    assert "假设性解释" in p
    assert "这可能是因为" in p
    assert "300 字" in p


def test_confirm_prompt_carries_revision_notes():
    """用户修正意见必须传入下一次确认生成。"""
    p = confirm_prompt({"dimensions": {}, "rounds": 3}, "你只是把我的回复拼凑成一段话，没有深入分析")
    assert "拼凑" in p
    assert "加深分析" in p


def test_question_prompt_requires_bridging():
    """提问 prompt 必须基于对方最近发言，禁止问卷式。"""
    p = question_prompt(DIMENSIONS[0], "（尚无）", "我最近因为考研的事很焦虑",
                        "trait_energy: 缺1")
    assert "对方刚才的发言" in p
    assert "我最近因为考研的事很焦虑" in p
    assert "不要像问卷" in p
    assert "呼应" in p
