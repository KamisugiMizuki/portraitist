"""终止判定器单测（DESIGN.md §5.3 终止条件 C-1~C-4 + 上限）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.engine import Engine
from portraitist.evidence import new_session


def make_engine(rounds_stats=None, contradiction=None, reflection=False, rounds=0):
    """构造一个带指定状态的 Engine（不连 LLM）。"""
    session = new_session()
    session["rounds"] = rounds
    session["round_stats"] = rounds_stats or []
    if contradiction:
        session["contradictions"].append(
            {"b_quote": contradiction, "conflicts_with": "旧陈述", "hint": "",
             "b_round": 1, "resolved": False, "resolution": ""}
        )
    if reflection:
        session["reflection"]["triggered"] = True
        session["reflection"]["round"] = 3
    from portraitist.llm import LLMGateway
    return Engine(session, None, {"max_rounds": 12, "anchors_per_dimension": 2,
                                  "reflection_grace_rounds": 8, "c3_window_rounds": 3,
                                  "c3_max_new_anchors": 1}, "sessions")


def test_c1_all_saturated():
    e = make_engine()
    for d in e.session["dimensions"]:
        e.session["dimensions"][d]["saturated"] = True
    term = e._evaluate_termination(5)
    assert term["c1"] is True


def test_c1_not_saturated():
    e = make_engine()
    assert e._evaluate_termination(5)["c1"] is False


def test_c2_unresolved_blocks():
    e = make_engine(contradiction="我怕被团队抛弃")
    assert e._evaluate_termination(5)["c2"] is False


def test_c2_resolved_passes():
    e = make_engine(contradiction="我怕被团队抛弃")
    e.session["contradictions"][0]["resolved"] = True
    assert e._evaluate_termination(5)["c2"] is True


def test_c3_window_quiet():
    # 最近 3 轮无新增信息（锚点 0）→ c3 True
    stats = [
        {"round": r, "new_anchors": 0, "new_contradictions": 0, "new_narratives": 0, "reflection": False}
        for r in (1, 2, 3)
    ]
    e = make_engine(rounds_stats=stats, rounds=3)
    term = e._evaluate_termination(3)
    assert term["c3"] is True


def test_c3_window_at_limit():
    # 窗口内锚点恰好 1（上限内）→ c3 True
    stats = [
        {"round": 1, "new_anchors": 0, "new_contradictions": 0, "new_narratives": 0, "reflection": False},
        {"round": 2, "new_anchors": 1, "new_contradictions": 0, "new_narratives": 0, "reflection": False},
        {"round": 3, "new_anchors": 0, "new_contradictions": 0, "new_narratives": 0, "reflection": False},
    ]
    e = make_engine(rounds_stats=stats, rounds=3)
    assert e._evaluate_termination(3)["c3"] is True


def test_c3_recent_new_info():
    # 窗口内仍有新锚点 → c3 False
    stats = [
        {"round": r, "new_anchors": 2, "new_contradictions": 0, "new_narratives": 0, "reflection": False}
        for r in (1, 2)
    ] + [{"round": 3, "new_anchors": 2, "new_contradictions": 0, "new_narratives": 0, "reflection": False}]
    e = make_engine(rounds_stats=stats, rounds=3)
    assert e._evaluate_termination(3)["c3"] is False


def test_c3_window_too_short():
    stats = [{"round": 1, "new_anchors": 0, "new_contradictions": 0, "new_narratives": 0, "reflection": False}]
    e = make_engine(rounds_stats=stats, rounds=1)
    assert e._evaluate_termination(1)["c3"] is False


def test_c4_reflection():
    e = make_engine(reflection=True)
    assert e._evaluate_termination(5)["c4"] is True


def test_c4_skipped_after_grace():
    e = make_engine(rounds=8)
    term = e._evaluate_termination(8)
    assert term["c4"] is False
    assert term["c4_skipped"] is True


def test_c4_not_skipped_early():
    e = make_engine(rounds=4)
    term = e._evaluate_termination(4)
    assert term["c4_skipped"] is False


def test_done_full_conditions():
    e = make_engine(reflection=True, rounds=5)
    for d in e.session["dimensions"]:
        e.session["dimensions"][d]["saturated"] = True
    term = e._evaluate_termination(5)
    assert term["done"] is True


def test_done_not_without_saturation():
    e = make_engine(reflection=True, rounds=5)
    term = e._evaluate_termination(5)
    assert term["done"] is False


def test_done_by_12_round_cap():
    e = make_engine(rounds=12)
    term = e._evaluate_termination(12)
    assert term["reached_cap"] is True
    assert term["done"] is True


def test_done_by_c3_plus_saturation():
    # 无反思但 8 轮后 c4_skipped，配合饱和与信息枯竭 → done
    stats = [
        {"round": r, "new_anchors": 0, "new_contradictions": 0, "new_narratives": 0, "reflection": False}
        for r in (8, 9, 10)
    ]
    e = make_engine(rounds_stats=stats, rounds=10)
    for d in e.session["dimensions"]:
        e.session["dimensions"][d]["saturated"] = True
    term = e._evaluate_termination(10)
    assert term["c3"] is True and term["c4_skipped"] is True
    assert term["done"] is True
