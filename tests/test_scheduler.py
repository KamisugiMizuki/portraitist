"""维度调度器单测：未解决矛盾优先 > 最欠饱和维度。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.dimensions import DIMENSIONS
from portraitist.engine import Engine
from portraitist.evidence import new_session


def make_engine():
    session = new_session()
    return Engine(session, None, {}, "sessions")


def test_initial_picks_first_dimension():
    e = make_engine()
    kind, payload = e._pick_next()
    assert kind == "probe"
    assert payload["id"] == DIMENSIONS[0]["id"]


def test_picks_least_saturated():
    e = make_engine()
    # trait_order 已有 1 锚点，其余 0 → 应选第一个 0 锚点维度
    e.session["dimensions"]["trait_order"]["anchors"].append({"quote": "x", "round": 1})
    kind, payload = e._pick_next()
    assert kind == "probe"
    assert payload["id"] != "trait_order"
    assert e.session["dimensions"][payload["id"]]["anchors"] == []


def test_unresolved_contradiction_first():
    e = make_engine()
    e.session["contradictions"].append(
        {"b_quote": "我其实很怕被团队抛弃", "conflicts_with": "我喜欢独处",
         "hint": "", "b_round": 2, "resolved": False, "resolution": ""}
    )
    kind, payload = e._pick_next()
    assert kind == "clarify"
    assert payload["b_quote"] == "我其实很怕被团队抛弃"


def test_resolved_contradiction_ignored():
    e = make_engine()
    e.session["contradictions"].append(
        {"b_quote": "x", "conflicts_with": "y", "hint": "", "b_round": 2,
         "resolved": True, "resolution": "澄清"}
    )
    kind, payload = e._pick_next()
    assert kind == "probe"


def test_contradiction_overrides_saturation():
    e = make_engine()
    e.session["contradictions"].append(
        {"b_quote": "待澄清矛盾", "conflicts_with": "旧", "hint": "", "b_round": 1,
         "resolved": False, "resolution": ""}
    )
    for d in e.session["dimensions"]:
        e.session["dimensions"][d]["saturated"] = True
    kind, payload = e._pick_next()
    assert kind == "clarify"
