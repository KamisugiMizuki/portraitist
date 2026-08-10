"""后端 API 冒烟测试（M3）：会话生命周期 + OpenAI 兼容口。使用 FakeGateway 不触真实 LLM。"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("PORTRAITIST_SESSIONS_DIR", tempfile.mkdtemp(prefix="hermes-api-test-"))

from fastapi.testclient import TestClient  # noqa: E402

# 用 FakeGateway 替换真实网关：构造最小假配置
import yaml  # noqa: E402

from portraitist.engine import Engine  # noqa: E402
from portraitist.evidence import new_session  # noqa: E402

import app.main as main  # noqa: E402


class FakeGateway:
    chat_model = "fake-chat"
    report_model = "fake-report"

    def __init__(self):
        self.extraction = {"anchors": [], "narratives": [], "contradictions": [],
                           "reflection": {"triggered": False, "quote": ""}, "crisis": False}
        self.report_md = (
            "「本分析基于对话模型推演，旨在促进自我觉察，不具备临床诊断或职业测评效度。」\n\n"
            "1. 核心特质图谱\n开放性：依据充分。依据：轮次1·「我周末会去逛美术馆」。\n"
            "2. 深层动力引擎\n主导驱动力：自主。依据：轮次1·「我周末会去逛美术馆」。\n"
            "3. 关系剧本与防御机制\n依恋策略：安全型。依据：轮次1·「我周末会去逛美术馆」。\n"
            "4. 生命叙事的主线逻辑\n你的人生故事是关于藏与寻的剧本，有天分的孩子学会了把真正的自己藏起来，在关系中寻找既能被确认又安全的角落，最终学会温和地现身。\n"
            "5. 综合真实自我描述\n一段总结。依据：轮次1·「我周末会去逛美术馆」。\n"
            "6. 成长视角与盲点\n内在资源。依据：轮次1·「我周末会去逛美术馆」。\n"
        )

    def chat(self, system, user, **kw):
        if "生成画像确认请求" in user or "核心轮廓" in user:
            return "感觉你是一个在独处中充电、但需要群体确认存在的人。这和你对自己的体感接近吗？"
        if "请基于以下访谈证据生成完整报告" in user:
            return self.report_md
        return "你提到周末喜欢在家待着，能说说独处时一般做什么吗？"

    def chat_json(self, system, user, **kw):
        return dict(self.extraction)


def _install_fake(tmp_dir: str) -> None:
    """把 SessionStore 指向临时目录 + FakeGateway。"""
    main.SESSIONS_DIR = tmp_dir
    main.STORE = main.SessionStore()
    main.STORE._gateway = FakeGateway()
    main.STORE._config = {
        "backend": "remote", "chat_model": "fake-chat", "report_model": "fake-report",
        "max_rounds": 3, "max_clarify_rounds": 1,
        "anchors_per_dimension": 2, "reflection_grace_rounds": 8,
        "c3_window_rounds": 3, "c3_max_new_anchors": 1,
    }


def test_session_lifecycle():
    tmp = tempfile.mkdtemp(prefix="hermes-api-")
    _install_fake(tmp)
    client = TestClient(main.app)

    # 创建会话
    r = client.post("/api/sessions")
    assert r.status_code == 200, r.text
    data = r.json()
    sid = data["session_id"]
    assert data["status"] == "active"
    assert "先说说你最近的状态" in data["text"]

    # 发送消息（active → run_round）
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "最近有点纠结考研的事"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] in ("active", "confirming")
    assert data["text"]

    # 状态徽章数据
    r = client.get(f"/api/sessions/{sid}/status")
    assert r.status_code == 200
    st = r.json()
    assert st["status"] in ("active", "confirming")
    assert st["rounds"] >= 1
    assert "dimensions" in st and st["dimension_total"] == 11

    # 列表包含该会话
    r = client.get("/api/sessions")
    assert any(s["session_id"] == sid for s in r.json()["sessions"])

    # 详情
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["session_id"] == sid

    # 配置回显
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["max_rounds"] == 3

    # 删除
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 404


def test_openai_compat_endpoint():
    tmp = tempfile.mkdtemp(prefix="hermes-api-")
    _install_fake(tmp)
    client = TestClient(main.app)

    # 无 session tag：首次请求自动创建会话
    r = client.post("/v1/chat/completions", json={
        "model": "fake-chat",
        "messages": [{"role": "user", "content": "最近在准备考研，但没什么动力"}],
        "stream": False,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"]
    assert data["choices"][0]["finish_reason"] == "stop"

    # 带 session tag：映射到已有会话
    sessions = main.STORE.list()
    sid = sessions[0]["session_id"]
    r = client.post("/v1/chat/completions", json={
        "model": "fake-chat",
        "messages": [
            {"role": "system", "content": f"[portraitist-session: {sid}]"},
            {"role": "user", "content": "其实我觉得一个人待着也挺好的"},
        ],
        "stream": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"]

    # stream=true：SSE 伪流式
    r = client.post("/v1/chat/completions", json={
        "model": "fake-chat",
        "messages": [
            {"role": "system", "content": f"[portraitist-session: {sid}]"},
            {"role": "user", "content": "再说说最近的事吧"},
        ],
        "stream": True,
    })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    body = r.text
    assert "[DONE]" in body

    # 不存在的会话 → 404
    r = client.post("/v1/chat/completions", json={
        "model": "fake-chat",
        "messages": [
            {"role": "system", "content": "[portraitist-session: deadbeef]"},
            {"role": "user", "content": "你好"},
        ],
    })
    assert r.status_code == 404


def test_report_endpoint():
    tmp = tempfile.mkdtemp(prefix="hermes-api-")
    _install_fake(tmp)
    client = TestClient(main.app)

    # 用引擎直跑一个 completed 会话（绕过真实 LLM 对话：直接构造）
    engine, _ = main.STORE.create()
    sid = engine.session["session_id"]
    # 注入 3 轮锚点使其 cap 完成
    for rnd in range(1, 4):
        engine.session["dimensions"][f"d{rnd}" if False else "trait_energy"]["anchors"].append(
            {"quote": "我周末会去逛美术馆", "scene": "周末", "direction": "x", "round": rnd})
        engine.session["round_stats"].append(
            {"round": rnd, "new_anchors": 1, "new_contradictions": 0,
             "new_narratives": 0, "reflection": False})
    engine.session["rounds"] = 3
    from portraitist.evidence import refresh_saturation
    refresh_saturation(engine.session, 2)
    # 触发确认 → 接受 → 报告
    engine._save()
    engine.session["status"] = "confirming"
    result = engine.handle_confirmation("认可")
    assert result["state"] == "completed"

    r = client.get(f"/api/sessions/{sid}/report")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "核心特质图谱" in data["markdown"]
    assert data["checks"]["ok"] is True

    # 未完成会话的报告 → 404
    engine2, _ = main.STORE.create()
    r = client.get(f"/api/sessions/{engine2.session['session_id']}/report")
    assert r.status_code == 404
