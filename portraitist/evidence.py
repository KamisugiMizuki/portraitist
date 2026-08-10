"""证据库：访谈会话的结构化证据存储（DESIGN.md §5.2）。

核心原则：证据只锚定用户的显式陈述（原话 + 具体场景），
direction 等方向标签基于行为描述内容，不由 LLM 印象打分决定。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

from .dimensions import DIMENSION_IDS, DIRECTIONS_BY_DIM
from .prompts import NAME_TO_ID

# 关键词 → 维度 id 模糊匹配（提取器可能输出"内向性""依恋""人生故事"等变体）
KEYWORD_TO_ID = {
    "能量": "trait_energy", "外向": "trait_energy", "内向": "trait_energy",
    "秩序": "trait_order", "条理": "trait_order", "计划": "trait_order",
    "情绪": "trait_emotion", "敏感": "trait_emotion",
    "开放": "trait_openness",
    "协作": "trait_agree", "宜人": "trait_agree",
    "驱力": "motive_drive", "动机": "motive_drive",
    "价值": "motive_value",
    "自我": "self_discrepancy", "理想": "self_discrepancy",
    "依恋": "rel_attachment",
    "防御": "rel_defense", "压力反应": "rel_defense",
    "叙事": "narrative_identity", "人生故事": "narrative_identity", "生命故事": "narrative_identity",
}


def resolve_dimension(dim: str) -> str:
    """维度标识容错：英文 id > 精确中文名 > 关键词包含匹配。"""
    if dim in DIMENSION_IDS:
        return dim
    if dim in NAME_TO_ID:
        return NAME_TO_ID[dim]
    for kw, did in KEYWORD_TO_ID.items():
        if kw in dim:
            return did
    return ""

VALID_ANCHOR_DIRECTIONS = {d: set(v) for d, v in DIRECTIONS_BY_DIM.items()}
NARRATIVE_TYPES = {"high", "low", "turning"}

CRISIS_KEYWORDS = [
    "自杀", "自残", "不想活", "活不下去", "结束生命", "伤害自己",
    "了结", "轻生", "si了算了", "死了一了百了",
]


def new_session() -> dict:
    return {
        "session_id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rounds": 0,
        "status": "active",  # active | confirming | completed
        "dimensions": {d: {"anchors": [], "saturated": False} for d in DIMENSION_IDS},
        "contradictions": [],
        "narratives": [],
        "reflection": {"triggered": False, "quote": "", "round": 0},
        "crisis": {"triggered": False, "round": 0},
        "termination": {
            "c1": False, "c2": False, "c3": False, "c4": False,
            "c4_skipped": False, "reached_cap": False, "notes": "",
        },
        "confirmation": {"requested": False, "response": "", "revision_notes": ""},
        "report": {"generated_at": "", "path": "", "checks": {}},
    }


def save_session(session: dict, sessions_dir: str) -> str:
    path = os.path.join(sessions_dir, session["session_id"], "evidence.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return path


def load_session(session_id: str, sessions_dir: str) -> dict:
    with open(os.path.join(sessions_dir, session_id, "evidence.json"), encoding="utf-8") as f:
        return json.load(f)


def append_transcript(session: dict, sessions_dir: str, entry: dict) -> None:
    path = os.path.join(sessions_dir, session["session_id"], "transcript.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def anchor_count(session: dict, dim_id: str) -> int:
    return len(session["dimensions"][dim_id]["anchors"])


def anchor_summary(session: dict, dim_id: str, max_quotes: int = 4) -> str:
    """供提问器/提取器使用的维度锚点摘要（避免重复提问、检测矛盾）。"""
    anchors = session["dimensions"][dim_id]["anchors"]
    if not anchors:
        return "（尚无）"
    lines = []
    for a in anchors[-max_quotes:]:
        q = a["quote"].replace("\n", " ")
        if len(q) > 80:
            q = q[:80] + "…"
        lines.append(f"- 第{a['round']}轮: 「{q}」")
    return "\n".join(lines)


def merge_extraction(session: dict, round_no: int, extraction: dict) -> dict:
    """将提取器输出合并入证据库。返回合并统计（供测试与日志）。"""
    stats = {"anchors": 0, "narratives": 0, "contradictions": 0, "reflection": False, "crisis": False,
             "dropped": 0}

    # 危机信号（提取器标注 + 关键词层双保险）
    crisis = bool(extraction.get("crisis"))
    if not crisis:
        reply = str(extraction.get("_raw_reply", ""))
        crisis = any(kw in reply for kw in CRISIS_KEYWORDS)
    if crisis and not session["crisis"]["triggered"]:
        session["crisis"]["triggered"] = True
        session["crisis"]["round"] = round_no
        stats["crisis"] = True

    # 行为锚点
    for a in extraction.get("anchors") or []:
        dim = resolve_dimension(a.get("dimension", ""))
        quote = (a.get("quote") or "").strip()
        scene = (a.get("scene") or "").strip()
        if dim not in DIMENSION_IDS or not quote:
            stats["dropped"] += 1
            continue
        direction = a.get("direction", "mixed")
        valid = VALID_ANCHOR_DIRECTIONS[dim]
        if valid and direction not in valid:
            direction = "mixed"
        session["dimensions"][dim]["anchors"].append(
            {
                "quote": quote,
                "scene": scene,
                "direction": direction,
                "round": round_no,
                "confidence": "high" if scene else "medium",
            }
        )
        stats["anchors"] += 1

    # 叙事事件
    for n in extraction.get("narratives") or []:
        ntype = n.get("type", "")
        story = (n.get("story") or "").strip()
        if ntype not in NARRATIVE_TYPES or not story:
            continue
        session["narratives"].append({"type": ntype, "story": story, "round": round_no})
        stats["narratives"] += 1

    # 矛盾信号：resolved=true 时闭环匹配未解决矛盾；否则追加新矛盾
    for c in extraction.get("contradictions") or []:
        b_quote = (c.get("b_quote") or "").strip()
        if not b_quote:
            continue
        if c.get("resolved"):
            conflicts = (c.get("conflicts_with") or "").strip()
            target = None
            for u in session["contradictions"]:
                if u["resolved"]:
                    continue
                # 匹配池 = 矛盾的双方表述（b_quote + conflicts_with），澄清可能指向任一面
                hay = u["b_quote"] + " " + u.get("conflicts_with", "")
                if (
                    b_quote in hay or hay in b_quote
                    or (conflicts and (conflicts in hay or hay in conflicts))
                ):
                    target = u
                    break
            if target:
                target["resolved"] = True
                target["resolution"] = b_quote
                target["resolution_round"] = round_no
                stats["contradictions"] += 1
                continue
            # 澄清匹配失败（无对应矛盾）→ 丢弃，不凭空产生条目
            stats["dropped"] += 1
            continue
        session["contradictions"].append(
            {
                "b_quote": b_quote,
                "conflicts_with": (c.get("conflicts_with") or "").strip(),
                "hint": (c.get("hint") or "").strip(),
                "b_round": round_no,
                "resolved": False,
                "resolution": "",
            }
        )
        stats["contradictions"] += 1

    # 深层反思（C-4）
    refl = extraction.get("reflection") or {}
    if refl.get("triggered") and not session["reflection"]["triggered"]:
        session["reflection"]["triggered"] = True
        session["reflection"]["quote"] = (refl.get("quote") or "").strip()
        session["reflection"]["round"] = round_no
        stats["reflection"] = True

    return stats


def refresh_saturation(session: dict, anchors_per_dimension: int) -> None:
    for d in DIMENSION_IDS:
        session["dimensions"][d]["saturated"] = anchor_count(session, d) >= anchors_per_dimension


def unresolved_contradictions(session: dict) -> list[dict]:
    return [c for c in session["contradictions"] if not c["resolved"]]


def evidence_bundle(session: dict) -> dict:
    """报告生成/确认环节使用的完整证据摘要（不含原始对话全文）。"""
    return {
        "rounds": session["rounds"],
        "dimensions": {
            d: {
                "anchors": session["dimensions"][d]["anchors"],
                "saturated": session["dimensions"][d]["saturated"],
            }
            for d in DIMENSION_IDS
        },
        "contradictions": session["contradictions"],
        "narratives": session["narratives"],
        "reflection": session["reflection"],
        "crisis": session["crisis"],
        "termination": session["termination"],
    }
