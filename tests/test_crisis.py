"""M4 危机边界测试：关键词层/LLM 信号/报告声明/触发后行为（DESIGN §7.3）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portraitist.engine import CRISIS_RESPONSE, Engine
from portraitist.evidence import new_session
from portraitist.llm import LLMGateway


class FakeGateway(LLMGateway):
    """脚本式网关：按序返回预设 JSON/文本。"""

    def __init__(self, extractions, chat_texts=None):
        self.extractions = list(extractions)
        self.chat_texts = list(chat_texts or [])
        self.report_model = "report-model"
        self.chat_model = "chat-model"

    def chat_json(self, system, user, **kwargs):
        if self.extractions:
            return self.extractions.pop(0)
        return {}

    def chat(self, system, user, **kwargs):
        if self.chat_texts:
            return self.chat_texts.pop(0)
        return "引导师提问"


def empty_extraction():
    return {
        "anchors": [], "contradictions": [], "narratives": [],
        "reflection": {"triggered": False, "quote": ""}, "crisis": False,
    }


def make_engine(gateway, tmp: str):
    session = new_session()
    engine = Engine(session, gateway, {"max_rounds": 5}, tmp)
    return engine, session


# ---------- 触发路径 ----------

def test_crisis_keyword_layer(tmp_path):
    """关键词层：不依赖提取器直接拦截，返回求助卡片，标记 crisis。"""
    gateway = FakeGateway([])
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    result = engine.run_round("有时候真的不想活了，感觉没意思")
    assert result["note"].startswith("crisis")
    assert result["text"] == CRISIS_RESPONSE
    assert session["crisis"]["triggered"] is True
    assert session["crisis"]["round"] == 1
    # 该轮不产生提取（无锚点入证据）
    assert all(len(d["anchors"]) == 0 for d in session["dimensions"].values())


def test_crisis_from_extractor(tmp_path):
    """LLM 信号层：提取器 crisis=true 时同样拦截。"""
    script = [empty_extraction()]
    script[0]["crisis"] = True
    gateway = FakeGateway(script)
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    result = engine.run_round("我最近很难受")
    assert result["note"].startswith("crisis")
    assert result["text"] == CRISIS_RESPONSE
    assert session["crisis"]["triggered"] is True


def test_crisis_then_continue(tmp_path):
    """触发后下一轮正常继续（只停止追问该话题，不终止访谈）。"""
    gateway = FakeGateway([empty_extraction(), empty_extraction()])
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    r1 = engine.run_round("我不想活了，压力太大了")
    assert r1["note"].startswith("crisis")

    r2 = engine.run_round("其实也就是最近工作太累了，休息一下应该会好")
    assert r2["note"] != "crisis"  # 正常推进
    assert session["crisis"]["triggered"] is True  # 标记保留


def test_crisis_no_followup_on_topic(tmp_path):
    """危机轮不产生锚点 → 后续追问不会指向危机内容（DESIGN：停止追问该话题）。"""
    gateway = FakeGateway([empty_extraction()])
    engine, session = make_engine(gateway, str(tmp_path))
    engine.first_question()

    engine.run_round("我不想活了")
    # 该轮未提取任何锚点
    assert all(len(d["anchors"]) == 0 for d in session["dimensions"].values())


# ---------- 报告声明 ----------

def test_crisis_report_declaration(tmp_path):
    """危机会话报告末尾追加求助指引 + 定位声明（不破坏六段校验）。"""
    from tests.test_report_checks import GOOD_REPORT, session_with_rounds

    gateway = FakeGateway([empty_extraction()], chat_texts=["邀请文本", GOOD_REPORT])
    session = session_with_rounds()
    session["crisis"]["triggered"] = True
    session["crisis"]["round"] = 2
    engine = Engine(session, gateway, {"max_rounds": 5}, str(tmp_path))
    session["status"] = "confirming"
    result = engine.handle_confirmation("认可")
    assert result["state"] == "completed"

    path = session["report"]["path"]
    with open(Path(str(tmp_path)) / path, encoding="utf-8") as f:
        content = f.read()
    assert "危机提示" in content
    assert "400-161-9995" in content
    assert "不提供危机干预" in content
    # 六段主体未被破坏（声明在末尾追加）
    assert "核心特质图谱" in content


def test_crisis_report_no_analysis():
    """危机内容不进入证据（该轮无锚点）→ 报告天然不含危机推测分析。"""
    # 由 test_crisis_keyword_layer 保证无锚点；此处验证 evidence_bundle 不含危机引用
    from portraitist.evidence import evidence_bundle
    session = new_session()
    session["crisis"]["triggered"] = True
    session["crisis"]["round"] = 1
    bundle = evidence_bundle(session)
    assert "自杀" not in bundle and "不想活" not in bundle


def test_normal_report_no_declaration(tmp_path):
    """非危机会话报告不含危机提示段。"""
    from tests.test_report_checks import GOOD_REPORT, session_with_rounds

    gateway = FakeGateway([empty_extraction()], chat_texts=["邀请文本", GOOD_REPORT])
    session = session_with_rounds()
    engine = Engine(session, gateway, {"max_rounds": 5}, str(tmp_path))
    session["status"] = "confirming"
    engine.handle_confirmation("认可")
    path = session["report"]["path"]
    with open(Path(str(tmp_path)) / path, encoding="utf-8") as f:
        content = f.read()
    assert "危机提示" not in content
