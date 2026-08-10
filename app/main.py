"""portraitist 本地 Web 后端（M3）。

FastAPI + 引擎接线。端点契约见 DESIGN.md §6.1：
- /api/sessions         GET/POST  —— 会话列表 / 新建访谈会话
- /api/sessions/{id}    GET/DELETE —— 会话详情 / 删除
- /api/sessions/{id}/chat POST   —— 发送一条用户消息（SSE 流式 AI 回复）
- /api/sessions/{id}/report GET —— 已生成报告（Markdown + 元数据）
- /api/sessions/{id}/status GET —— 引擎内部状态（阶段/维度覆盖/轮数，供 UI 徽章）
- /api/config           GET      —— 模型配置回显（只读）
- /v1/chat/completions  POST     —— OpenAI 兼容口（NextChat fork 前端直连）

运行：.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")
CONFIG_PATH = os.path.join(ROOT, "config.yaml")

from portraitist.engine import Engine
from portraitist.evidence import load_session, new_session
from portraitist.llm import LLMGateway

app = FastAPI(title="portraitist", version="0.1.0")

# 本地 Web：允许浏览器跨端口访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 会话存储 ----------

class SessionStore:
    """内存会话表 + sessions/ 目录持久化（引擎已落盘 evidence.json）。"""

    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}
        self._gateway: LLMGateway | None = None
        self._config: dict | None = None

    def _load_config(self) -> dict:
        if self._config is None:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        return self._config

    @property
    def gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = LLMGateway(self._load_config())
        return self._gateway

    def _engine(self, session: dict) -> Engine:
        return Engine(session, self.gateway, self._load_config(), SESSIONS_DIR)

    def create(self) -> Engine:
        engine = self._engine(new_session())
        text = engine.first_question()
        engine._transcript("assistant", text, {"kind": "invitation"})
        engine._save()
        self._engines[engine.session["session_id"]] = engine
        return engine

    @staticmethod
    def last_assistant_text(session_id: str) -> str:
        """从 transcript 文件读最后一条 assistant 消息（开场邀请/最近回复）。"""
        tpath = os.path.join(SESSIONS_DIR, session_id, "transcript.jsonl")
        if not os.path.exists(tpath):
            return ""
        for line in reversed(open(tpath, encoding="utf-8").readlines()):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("role") == "assistant":
                return e.get("content", "")
        return ""
    def get(self, session_id: str) -> Engine:
        if session_id in self._engines:
            return self._engines[session_id]
        path = os.path.join(SESSIONS_DIR, session_id)
        if not os.path.isdir(path):
            raise HTTPException(404, f"会话不存在: {session_id}")
        session = load_session(session_id, SESSIONS_DIR)
        engine = self._engine(session)
        self._engines[session_id] = engine
        return engine

    def list(self) -> list[dict]:
        out = []
        for sid in sorted(os.listdir(SESSIONS_DIR), reverse=True):
            path = os.path.join(SESSIONS_DIR, sid)
            ev = os.path.join(path, "evidence.json")
            if not os.path.isdir(path) or not os.path.exists(ev):
                continue
            try:
                session = load_session(sid, SESSIONS_DIR)
            except Exception:
                continue
            report = session.get("report") or {}
            out.append({
                "session_id": sid,
                "status": session.get("status", "active"),
                "rounds": session.get("rounds", 0),
                "created_at": session.get("created_at", ""),
                "has_report": bool(report.get("path")),
                "report_ok": (report.get("checks") or {}).get("ok", False),
            })
        return out

    def delete(self, session_id: str) -> None:
        import shutil
        path = os.path.join(SESSIONS_DIR, session_id)
        if not os.path.isdir(path):
            raise HTTPException(404, f"会话不存在: {session_id}")
        shutil.rmtree(path)
        self._engines.pop(session_id, None)


STORE = SessionStore()


def _public_status(engine: Engine) -> dict:
    """UI 徽章数据（DESIGN §6.1：active/confirming/completed + 覆盖进度）。"""
    s = engine.session
    dims = []
    for dim_id, info in s["dimensions"].items():
        dims.append({
            "id": dim_id,
            "name": info.get("name", dim_id),
            "anchors": len(info.get("anchors", [])),
            "saturated": bool(info.get("saturated")),
        })
    contradictions = [c for c in s.get("contradictions", []) if not c.get("resolved")]
    return {
        "status": s.get("status", "active"),
        "rounds": s.get("rounds", 0),
        "max_rounds": engine.max_rounds,
        "dimensions": dims,
        "saturated_count": sum(1 for d in dims if d["saturated"]),
        "dimension_total": len(dims),
        "unresolved_contradictions": len(contradictions),
        "reflection_triggered": bool((s.get("reflection") or {}).get("triggered")),
        "termination": s.get("termination"),
    }


# ---------- 请求/响应模型 ----------

class ChatRequest(BaseModel):
    message: str


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str
    text: str


class ChatResponse(BaseModel):
    session_id: str
    status: str
    text: str
    note: str = ""


# ---------- API 端点 ----------

@app.get("/api/sessions")
def list_sessions():
    return {"sessions": STORE.list()}


@app.post("/api/sessions", response_model=SessionCreateResponse)
def create_session():
    engine = STORE.create()
    return {
        "session_id": engine.session["session_id"],
        "status": engine.session["status"],
        "text": STORE.last_assistant_text(engine.session["session_id"]),
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    engine = STORE.get(session_id)
    s = engine.session
    transcript = []
    tpath = os.path.join(SESSIONS_DIR, session_id, "transcript.jsonl")
    if os.path.exists(tpath):
        for line in open(tpath, encoding="utf-8"):
            try:
                transcript.append(json.loads(line))
            except Exception:
                continue
    return {
        "session_id": session_id,
        "status": s.get("status"),
        "rounds": s.get("rounds", 0),
        "transcript": transcript,
        "coverage": _public_status(engine),
        "report": s.get("report"),
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    STORE.delete(session_id)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(session_id: str, req: ChatRequest):
    engine = STORE.get(session_id)
    if engine.session.get("status") == "completed":
        raise HTTPException(409, "会话已完成，无法继续对话")
    if engine.session.get("status") == "confirming":
        result = engine.handle_confirmation(req.message)
    else:
        result = engine.run_round(req.message)
    return {
        "session_id": session_id,
        "status": result["state"],
        "text": result["text"],
        "note": result.get("note", ""),
    }


@app.get("/api/sessions/{session_id}/status")
def session_status(session_id: str):
    engine = STORE.get(session_id)
    return _public_status(engine)


@app.get("/api/sessions/{session_id}/report")
def session_report(session_id: str):
    engine = STORE.get(session_id)
    report = engine.session.get("report") or {}
    path = os.path.join(SESSIONS_DIR, session_id, "report.md")
    if not os.path.exists(path):
        raise HTTPException(404, "报告尚未生成")
    with open(path, encoding="utf-8") as f:
        md = f.read()
    return {
        "session_id": session_id,
        "markdown": md,
        "checks": report.get("checks", {}),
        "generated_at": report.get("generated_at"),
    }


@app.get("/api/config")
def config_echo():
    cfg = STORE._load_config()
    return {
        "backend": cfg.get("backend", "remote"),
        "chat_model": cfg.get("chat_model", ""),
        "report_model": cfg.get("report_model", ""),
        "max_rounds": cfg.get("max_rounds", 14),
        "max_clarify_rounds": cfg.get("max_clarify_rounds", 3),
    }


# ---------- OpenAI 兼容口（NextChat fork 直连） ----------

SESSION_TAG_RE = re.compile(r"\[portraitist-session:\s*([a-f0-9]+)\]")


class OpenAIRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    stream: bool = False


@app.post("/v1/chat/completions")
def chat_completions(req: OpenAIRequest):
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")

    # 解析注入的 session_id（前端在首条消息前注入系统消息）
    session_id = ""
    for m in req.messages:
        if m.get("role") == "system":
            m_match = SESSION_TAG_RE.search(m.get("content", ""))
            if m_match:
                session_id = m_match.group(1)

    user_msgs = [m["content"] for m in req.messages if m.get("role") == "user"]
    if not user_msgs:
        raise HTTPException(400, "缺少用户消息")

    if session_id:
        engine = STORE.get(session_id)
        if engine.session.get("status") == "completed":
            # 已完成会话：直接返回报告提示，不进入引擎
            text = "本会话已生成报告，请到报告页查看。"
            result = {"state": "completed", "text": text, "note": "completed"}
        else:
            result = engine.handle_confirmation(user_msgs[-1]) if engine.session.get("status") == "confirming" else engine.run_round(user_msgs[-1])
            text = result["text"]
    else:
        engine = STORE.create()
        result = engine.run_round(user_msgs[-1])
        text = result["text"]
        session_id = engine.session["session_id"]

    note = result.get("note", "")
    _ = note
    payload = {
        "id": f"chatcmpl-{session_id[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or "portraitist",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
    }
    if not req.stream:
        return payload

    # SSE 伪流式：完整文本分块发送（NextChat 解析器兼容）
    def gen():
        for i in range(0, len(text), 3):
            chunk = text[i:i + 3]
            yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0}]}, ensure_ascii=False)}\n\n"
            time.sleep(0.01)
        yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}
