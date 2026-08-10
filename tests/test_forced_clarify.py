"""强制澄清机制测试：确认前未解决矛盾必须先澄清（用户拍板，2026-08-11）。"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.engine import Engine
from portraitist.evidence import new_session


def empty_extraction():
    return {"anchors": [], "narratives": [], "contradictions": [],
            "reflection": {"triggered": False, "quote": ""}, "crisis": False}


class FakeGateway:
    chat_model = "fake-chat"
    report_model = "fake-report"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, system, user, **kw):
        self.calls.append(("chat", user[:40]))
        if "矛盾" in user:
            return "你说喜欢一个人待着，又说很依赖朋友——这两者是怎么共存的呢？"
        if "生成一句自然的提问" in user or "追问一个具体的生活场景" in user:
            return "能具体说说吗？"
        return "（回复）"

    def chat_json(self, system, user, **kw):
        return self.script.pop(0) if self.script else empty_extraction()


def make_engine(script, max_rounds=14, max_clarify=3):
    session = new_session()
    return Engine(session, FakeGateway(script), {
        "max_rounds": max_rounds, "max_clarify_rounds": max_clarify,
        "anchors_per_dimension": 2, "reflection_grace_rounds": 8,
        "c3_window_rounds": 3, "c3_max_new_anchors": 1,
    }, tempfile.mkdtemp(prefix="hermes-test-"))


def test_forced_clarify_before_confirm():
    """矛盾在 cap 轮产生且未解决 → 先强制澄清，不进 confirming；澄清后正常确认。"""
    script = [empty_extraction() for _ in range(3)]
    # 第 2 轮（cap 轮）：产生矛盾
    script[1]["contradictions"] = [{"resolved": False, "b_quote": "我喜欢一个人待着",
                                    "conflicts_with": "我很依赖朋友", "hint": ""}]
    # 第 3 轮：用户澄清，矛盾 resolved
    script[2]["contradictions"] = [{"resolved": True, "b_quote": "一个人待着充电但需要朋友在旁边",
                                    "conflicts_with": "我喜欢一个人待着", "hint": ""}]
    e = make_engine(script, max_rounds=2, max_clarify=3)
    e.first_question()
    r1 = e.run_round("（回复）")
    assert r1["state"] == "active"
    # 第 2 轮 cap 触发 + 矛盾未解决 → 强制澄清
    r2 = e.run_round("（回复）")
    assert r2["note"] == "clarify_forced", r2
    assert r2["state"] == "active", "cap 触发但矛盾未解决时不应进入 confirming"
    assert "强制澄清" in e.session["termination"]["notes"]
    # 第 3 轮：用户澄清后矛盾解决 → 进入 confirming
    r3 = e.run_round("（回复）")
    assert r3["state"] == "confirming", r3
    assert all(c["resolved"] for c in e.session["contradictions"])


def test_clarify_exhaustion_forces_confirm():
    """澄清轮耗尽（3 轮）仍无法解决 → 强制进入 confirming（防死锁）。"""
    script = [empty_extraction() for _ in range(6)]
    for s in script:
        s["contradictions"] = [{"resolved": False, "b_quote": "矛盾A",
                                "conflicts_with": "矛盾B", "hint": ""}]
    e = make_engine(script, max_rounds=3, max_clarify=3)
    e.first_question()
    notes = []
    for _ in range(6):
        r = e.run_round("（回复）")
        notes.append(r["note"])
        if r["state"] == "confirming":
            break
    # rounds 1-2 正常（cap 前），round 3 起 cap 触发 → 3 轮强制澄清 → 耗尽后确认
    assert notes.count("clarify_forced") == 3, notes
    assert e.session["status"] == "confirming", e.session["status"]


def test_forced_clarify_uses_clarify_question():
    """强制澄清轮的问题必须是矛盾澄清问法（含矛盾双方），而非维度 probe。"""
    script = [empty_extraction() for _ in range(2)]
    script[1]["contradictions"] = [{"resolved": False, "b_quote": "我讨厌被指挥",
                                    "conflicts_with": "我合群", "hint": ""}]
    e = make_engine(script, max_rounds=2, max_clarify=3)
    e.first_question()
    r1 = e.run_round("（回复）")
    assert r1["state"] == "active"
    r2 = e.run_round("（回复）")
    assert r2["note"] == "clarify_forced"
    assert "共存" in r2["text"], r2["text"]


def test_default_max_rounds_14():
    """默认 max_rounds 提升到 14（用户拍板）。"""
    e = make_engine([], max_rounds=14)
    assert e.max_rounds == 14
    assert e.max_clarify_rounds == 3
