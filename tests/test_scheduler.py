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


def test_recent_probe_dimension_skipped():
    """连续调用时最近 2 轮 probe 过的维度被跳过（防绕圈）。"""
    e = make_engine()
    # 第一次调用会选 trait_energy（第一个维度）
    kind, p1 = e._pick_next()
    assert p1["id"] == "trait_energy"
    # 第二次调用不应再选 trait_energy
    kind, p2 = e._pick_next()
    assert p2["id"] != "trait_energy"
    # 第三次调用：trait_energy 仍在 recent（最近2轮）→ 继续跳过
    kind, p3 = e._pick_next()
    assert p3["id"] not in ("trait_energy", p2["id"])


def test_recent_probe_allows_only_remaining():
    """若所有欠饱和维度都在 recent 中，则回退到全部候选（不死锁）。"""
    e = make_engine()
    # 让 trait_order 成为唯一欠饱和维度（其他维度都满）
    for d in e.session["dimensions"]:
        if d != "trait_order":
            e.session["dimensions"][d]["anchors"] = [{"quote": "x", "round": 1}] * 2
            e.session["dimensions"][d]["saturated"] = True
    # 先 probe trait_order（recent 里是它）
    kind, p = e._pick_next()
    assert p["id"] == "trait_order"
    # 再次调用：trait_order 在 recent，其他维度都饱和 → 回退到全部候选 → 仍选 trait_order
    kind, p2 = e._pick_next()
    assert p2["id"] == "trait_order"
