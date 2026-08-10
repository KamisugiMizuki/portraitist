"""mock LLM 全流程测试：FakeGateway 驱动状态机跑完整访谈。

场景：
1. 正常完成（锚点覆盖 + 矛盾闭环 + 反思触发）→ completed + 报告通过校验
2. 无反思 → c4_skipped 弹性跳过路径
3. 提取永远为空 → 12 轮上限强制进入确认
4. 危机信号（提取器标注 + 关键词层）→ 危机回应
5. 画像确认被否认 → 回到 active 继续采集
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.engine import CRISIS_RESPONSE, Engine
from portraitist.evidence import new_session
from portraitist.report import check_report

GOOD_REPORT = """「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度，请保持批判性视角参考。」

1. 核心特质图谱
- 开放性：依据充分。依据：轮次2·「轮2关于trait_order的原话A」。
- 尽责性：初步。依据：轮次3·「轮3关于trait_emotion的原话A」。

2. 深层动力引擎
- 主导驱动力：自主。依据：轮次4·「轮4关于trait_openness的原话A」。

3. 关系剧本与防御机制
- 依恋策略：安全型。依据：轮次5·「轮5关于trait_agree的原话A」。

4. 生命叙事的主线逻辑
- 一个不断证明自己的逆袭者。依据：轮次6·「轮6关于motive_drive的原话A」。

5. ✨ 综合真实自我描述
- 一段总结。依据：轮次7·「轮7关于motive_value的原话A」。

6. 成长视角与盲点
- 内在资源。依据：轮次8·「轮8关于self_discrepancy的原话A」。
"""


def anchor(dim, quote, direction="mixed"):
    return {"dimension": dim, "quote": quote, "scene": "某场景", "direction": direction}


def empty_extraction():
    return {"anchors": [], "narratives": [], "contradictions": [],
            "reflection": {"triggered": False, "quote": ""}, "crisis": False}


class FakeGateway:
    """按脚本返回提取结果；文本生成返回固定文案。"""

    def __init__(self, extract_script):
        self.extract_script = list(extract_script)
        self.extract_calls = 0
        self.chat_model = "fake-chat"
        self.report_model = "fake-report"

    def chat(self, system, user, **kw):
        if "生成一句自然的提问" in user or "追问一个具体的生活场景" in user:
            return "可以跟我讲讲你在这方面的具体经历吗？"
        if "口语化" in user:
            return "我感觉到你是一个重视自主、习惯独处但又渴望连接的人——这和你对自己的体感接近吗？"
        if system.startswith("你是一位心理画像报告撰写者"):
            return GOOD_REPORT
        return "（默认回复）"

    def chat_json(self, system, user, **kw):
        self.extract_calls += 1
        if self.extract_script:
            return self.extract_script.pop(0)
        return empty_extraction()


def make_engine(gateway, tmpdir):
    session = new_session()
    return Engine(session, gateway, {"max_rounds": 12, "anchors_per_dimension": 2,
                                     "reflection_grace_rounds": 8, "c3_window_rounds": 3,
                                     "c3_max_new_anchors": 1}, tmpdir), session


def normal_script():
    """11 轮：每轮 2 锚点覆盖 11 维度；轮4 矛盾；轮5 澄清；轮6 反思。"""
    dims = ["trait_energy", "trait_order", "trait_emotion", "trait_openness", "trait_agree",
            "motive_drive", "motive_value", "self_discrepancy", "rel_attachment",
            "rel_defense", "narrative_identity"]
    script = []
    for i, d in enumerate(dims):
        e = empty_extraction()
        e["anchors"] = [anchor(d, f"轮{i+1}关于{d}的原话A"), anchor(d, f"轮{i+1}关于{d}的原话B")]
        if i == 3:  # 轮4：报告矛盾
            e["contradictions"] = [{"resolved": False, "b_quote": "我讨厌被人指挥",
                                    "conflicts_with": "轮2我很合群的表述", "hint": "合群vs抗拒权威"}]
        if i == 4:  # 轮5：澄清轮（引擎先问矛盾）
            e["contradictions"] = [{"resolved": True, "b_quote": "我合群但讨厌被指挥，两回事",
                                    "conflicts_with": "我讨厌被人指挥", "hint": ""}]
        if i == 5:  # 轮6：反思触发
            e["reflection"] = {"triggered": True, "quote": "我从没想过这两件事有关联"}
        script.append(e)
    return script


def test_normal_completion(tmp_path):
    gateway = FakeGateway(normal_script())
    engine, session = make_engine(gateway, str(tmp_path))

    engine.first_question()
    states = []
    for _ in range(12):
        result = engine.run_round("（模拟用户回复）")
        states.append(result["state"])
        if result["state"] == "confirming":
            break

    assert session["status"] == "confirming"
    assert session["rounds"] <= 12
    assert session["termination"]["c1"] is True
    assert session["termination"]["c2"] is True
    assert session["termination"]["c4"] is True
    # 矛盾闭环成功
    assert all(c["resolved"] for c in session["contradictions"])

    # 确认 → 报告
    result = engine.handle_confirmation("认可")
    assert result["state"] == "completed"
    assert session["report"]["checks"]["ok"] is True, session["report"]["checks"]
    report_path = Path(result["text"])
    assert report_path.exists()
    md = report_path.read_text(encoding="utf-8")
    assert check_report(md, session)["ok"] is True


def test_no_reflection_uses_skip(tmp_path):
    script = []
    dims = ["trait_energy", "trait_order", "trait_emotion", "trait_openness", "trait_agree",
            "motive_drive", "motive_value", "self_discrepancy", "rel_attachment",
            "rel_defense", "narrative_identity"]
    for i, d in enumerate(dims):
        e = empty_extraction()
        e["anchors"] = [anchor(d, f"锚点{i}A"), anchor(d, f"锚点{i}B")]
        script.append(e)
    gateway = FakeGateway(script)
    engine, session = make_engine(gateway, str(tmp_path))

    engine.first_question()
    for _ in range(12):
        result = engine.run_round("回复")
        if result["state"] == "confirming":
            break

    assert session["status"] == "confirming"
    assert session["termination"]["c4"] is False
    assert session["termination"]["c4_skipped"] is True
    assert "深层反思未充分触发" in session["termination"]["notes"]


def test_empty_extraction_hits_12_round_cap(tmp_path):
    gateway = FakeGateway([])
    engine, session = make_engine(gateway, str(tmp_path))

    engine.first_question()
    confirming_at = None
    for i in range(15):
        result = engine.run_round("回复")
        if result["state"] == "confirming":
            confirming_at = i + 1
            break

    assert confirming_at == 12
    assert session["termination"]["reached_cap"] is True
    assert "12轮上限" in session["termination"]["notes"]


def test_crisis_from_extractor(tmp_path):
    script = [empty_extraction()]
    script[0]["crisis"] = True
    gateway = FakeGateway(script)
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    result = engine.run_round("我最近很难受")
    assert result["note"].startswith("crisis")
    assert result["text"] == CRISIS_RESPONSE
    assert session["crisis"]["triggered"] is True


def test_crisis_keyword_layer(tmp_path):
    """不依赖提取器，关键词层直接拦截。"""
    gateway = FakeGateway([])
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    result = engine.run_round("有时候真的不想活了")
    assert result["note"].startswith("crisis")
    assert session["crisis"]["triggered"] is True


def test_confirmation_rejected_returns_to_active(tmp_path):
    gateway = FakeGateway(normal_script())
    engine, session = make_engine(gateway, str(tmp_path))

    engine.first_question()
    for _ in range(12):
        result = engine.run_round("回复")
        if result["state"] == "confirming":
            break

    result = engine.handle_confirmation("我觉得不太对，我其实很享受独处")
    assert result["state"] == "active"
    assert session["status"] == "active"
    assert session["confirmation"]["response"] == "revised"
    assert session["confirmation"]["revision_notes"] == "我觉得不太对，我其实很享受独处"


def test_transcript_written(tmp_path):
    gateway = FakeGateway(normal_script())
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()
    engine.run_round("（模拟用户回复）")

    transcript = Path(tmp_path) / session["session_id"] / "transcript.jsonl"
    assert transcript.exists()
    lines = transcript.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # assistant(首问) + user + assistant
    assert any("assistant" in l for l in lines)
    assert any("user" in l for l in lines)


def test_evidence_json_written(tmp_path):
    gateway = FakeGateway(normal_script())
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()
    engine.run_round("回复")

    ev_path = Path(tmp_path) / session["session_id"] / "evidence.json"
    assert ev_path.exists()
