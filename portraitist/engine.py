"""访谈状态机（DESIGN.md §4.2、§5.3）。

程序层控制：维度调度、追问触发、终止判定（C-1~C-4 + 12 轮上限）、
画像确认、报告生成全部由本模块确定性执行；LLM 只负责生成提问、
结构化提取、生成报告三件事。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import prompts
from .dimensions import DIMENSIONS, DIMENSION_IDS
from .evidence import (
    anchor_count,
    anchor_summary,
    append_transcript,
    evidence_bundle,
    merge_extraction,
    refresh_saturation,
    save_session,
    unresolved_contradictions,
)
from .llm import LLMError, LLMGateway
from .report import check_report

CRISIS_RESPONSE = (
    "听到你说这些，我很担心你。我想先停一下，认真跟你说："
    "我没办法替代专业帮助，但你现在经历的痛苦值得被认真对待。"
    "如果你愿意，可以联系心理援助热线（如全国24小时心理援助热线 400-161-9995），"
    "或者当地的医院心理科/精神卫生中心，让专业人士陪着你。"
    "我们也可以先休息一下，等你好一些再继续聊。你想怎么安排都可以。"
)

CRISIS_REMINDER = "\n（提醒：本对话不提供危机干预，如有需要请拨打当地心理援助热线。）"


class Engine:
    def __init__(self, session: dict, gateway: LLMGateway, config: dict, sessions_dir: str):
        self.session = session
        self.gateway = gateway
        self.config = config
        self.sessions_dir = sessions_dir
        self.max_rounds = int(config.get("max_rounds", 12))
        self.anchors_per_dim = int(config.get("anchors_per_dimension", 2))
        self.grace_rounds = int(config.get("reflection_grace_rounds", 8))
        self.c3_window = int(config.get("c3_window_rounds", 3))
        self.c3_max_anchors = int(config.get("c3_max_new_anchors", 1))
        # 连续追问计数器：{dim_id: n}
        self._followups = {}
        # 最近 probe 过的维度（防连续选中同一维度，避免"绕圈"感）
        self._recent_probes = []
        # 上一轮引导师提问文本（提取器需要知道用户在回答什么问题）
        self._last_question = ""
        # 每轮合并统计（C-3 输入）
        self.session.setdefault("round_stats", [])

    # ---------- 持久化 ----------

    def _save(self):
        save_session(self.session, self.sessions_dir)

    def _transcript(self, role: str, content: str, extra: dict | None = None):
        entry = {"round": self.session["rounds"], "role": role, "content": content}
        if extra:
            entry.update(extra)
        append_transcript(self.session, self.sessions_dir, entry)

    # ---------- 调度 ----------

    def _pick_next(self) -> tuple[str, dict]:
        """选择下一步：未解决矛盾 > 最欠饱和维度（最近问过的维度暂时跳过）。"""
        contradictions = unresolved_contradictions(self.session)
        if contradictions:
            return ("clarify", contradictions[0])
        counts = [(d["id"], anchor_count(self.session, d["id"])) for d in DIMENSIONS]
        # 防连续：排除最近 2 轮 probe 过的维度；若排除后无欠饱和候选则全部纳入
        recent = self._recent_probes[-2:]
        candidates = [c for c in counts if c[0] not in recent]
        if not candidates or all(c[1] >= self.anchors_per_dim for c in candidates):
            candidates = counts
        candidates.sort(key=lambda x: x[1])
        dim_id = candidates[0][0]
        self._recent_probes.append(dim_id)
        return ("probe", next(d for d in DIMENSIONS if d["id"] == dim_id))

    # ---------- 主流程 ----------

    def first_question(self) -> str:
        """会话开场第一问。"""
        kind, payload = self._pick_next()
        assert kind == "probe"
        text = self._ask(payload, is_followup=False)
        self._last_question = text
        self._transcript("assistant", text)
        self._save()
        return text

    def run_round(self, user_reply: str) -> dict:
        """处理一条用户回复，返回 {'text': 回复文本, 'state': 会话状态, 'note': str}。"""
        self.session["rounds"] += 1
        round_no = self.session["rounds"]
        self._transcript("user", user_reply)

        # 危机关键词层（提取器之外的双保险）
        if any(kw in user_reply for kw in
               ["自杀", "自残", "不想活", "活不下去", "结束生命", "伤害自己", "轻生"]):
            self.session["crisis"]["triggered"] = True
            self.session["crisis"]["round"] = round_no
            self._transcript("assistant", CRISIS_RESPONSE, {"kind": "crisis"})
            self._save()
            return {"text": CRISIS_RESPONSE, "state": self.session["status"], "note": "crisis"}

        # 1. 结构化提取
        existing = self._existing_summary()
        try:
            extraction = self.gateway.chat_json(
                prompts.EXTRACT_SYSTEM,
                prompts.extract_prompt(self._last_question, user_reply, existing),
            )
        except LLMError as e:
            # 提取失败：不崩溃，按"无新锚点"处理并重试提问
            extraction = {}
            self._transcript("system", f"extract_failed: {e}")
        extraction["_raw_reply"] = user_reply

        # 2. 合并证据
        stats = merge_extraction(self.session, round_no, extraction)
        self.session["round_stats"].append(
            {
                "round": round_no,
                "new_anchors": stats["anchors"],
                "new_contradictions": stats["contradictions"],
                "new_narratives": stats["narratives"],
                "reflection": stats["reflection"],
            }
        )
        refresh_saturation(self.session, self.anchors_per_dim)

        # 3. 危机（提取器标注）
        if stats["crisis"]:
            self._transcript("assistant", CRISIS_RESPONSE, {"kind": "crisis"})
            self._save()
            return {"text": CRISIS_RESPONSE, "state": self.session["status"], "note": "crisis"}

        # 4. 终止判定
        term = self._evaluate_termination(round_no)
        if term["done"]:
            self.session["termination"] = {
                "c1": term["c1"], "c2": term["c2"], "c3": term["c3"],
                "c4": term["c4"], "c4_skipped": term["c4_skipped"],
                "reached_cap": term["reached_cap"], "notes": term["notes"],
            }
            self.session["status"] = "confirming"
            self.session["confirmation"]["requested"] = True
            confirm_text = self._ask_confirm()
            self._transcript("assistant", confirm_text, {"kind": "confirmation"})
            self._save()
            return {
                "text": confirm_text,
                "state": "confirming",
                "note": f"termination: {term['notes'] or 'all conditions met'}",
            }

        # 5. 正常提问（追问 or 新维度）
        text = self._next_question(user_reply, stats)
        self._last_question = text
        self._transcript("assistant", text)
        self._save()
        return {"text": text, "state": self.session["status"], "note": ""}

    def _next_question(self, user_reply: str, stats: dict) -> str:
        kind, payload = self._pick_next()
        if kind == "clarify":
            self._followups.clear()
            return self._ask_clarify(payload)
        # 追问判定：本轮无新锚点且该维度仍有提问空间
        dim = payload
        if stats["anchors"] == 0 and self._followups.get(dim["id"], 0) < 2:
            self._followups[dim["id"]] = self._followups.get(dim["id"], 0) + 1
            return self._ask(dim, is_followup=True, last_user=user_reply)
        self._followups.clear()
        return self._ask(dim, is_followup=False)

    def _coverage_status(self) -> str:
        """全局覆盖进度摘要（供提问器参考）。"""
        lines = []
        for dim in DIMENSIONS:
            n = anchor_count(self.session, dim["id"])
            mark = "已充分" if n >= self.anchors_per_dim else f"缺{self.anchors_per_dim - n}"
            lines.append(f"- {dim['name']}: {mark}（{n}个）")
        return "\n".join(lines)

    def _ask(self, dim: dict, *, is_followup: bool, last_user: str = "") -> str:
        try:
            return self.gateway.chat(
                prompts.ROLE_SYSTEM,
                prompts.question_prompt(
                    dim,
                    anchor_summary(self.session, dim["id"]),
                    last_user,
                    self._coverage_status(),
                    is_followup=is_followup,
                ),
                temperature=0.8,
                thinking=False,  # 提问是轻任务，关闭思考保延迟
            )
        except LLMError:
            # 提问失败兜底：用维度探测提示生成一句基础提问
            return f"可以跟我聊聊你在{dim['probe'].split('、')[0]}方面的一些经历吗？"

    def _ask_clarify(self, contradiction: dict) -> str:
        a_quote = contradiction.get("conflicts_with") or ""
        b_quote = contradiction["b_quote"]
        return (
            f"我注意到一个有点意思的地方：你之前提到{a_quote}，"
            f"而刚才你说「{b_quote}」。这两面听起来不太一样，"
            f"你能帮我理解一下它们是怎么在你身上共存的吗？"
        )

    def _ask_confirm(self) -> str:
        try:
            return self.gateway.chat(
                prompts.ROLE_SYSTEM,
                prompts.confirm_prompt(evidence_bundle(self.session)),
                temperature=0.7,
                max_tokens=600,
                thinking=False,
            )
        except LLMError:
            return "和你的对话里，我慢慢感觉到一种基调——这和你对自己的体感接近吗？"

    # ---------- 终止判定 ----------

    def _evaluate_termination(self, round_no: int) -> dict:
        c1 = all(dim["saturated"] for dim in self.session["dimensions"].values())
        c2 = len(unresolved_contradictions(self.session)) == 0
        window = self.session["round_stats"][-self.c3_window:]
        new_anchors = sum(w["new_anchors"] for w in window)
        new_other = sum(
            w["new_contradictions"] + w["new_narratives"] + (1 if w["reflection"] else 0)
            for w in window
        )
        c3 = len(window) >= self.c3_window and new_anchors <= self.c3_max_anchors and new_other == 0
        c4 = self.session["reflection"]["triggered"]
        c4_skipped = (not c4) and round_no >= self.grace_rounds
        reached_cap = round_no >= self.max_rounds

        done = (c1 and c2 and (c3 or c4 or c4_skipped)) or reached_cap
        notes = []
        if reached_cap:
            notes.append("达到12轮上限，生成阶段性画像")
        elif c4_skipped and not c4:
            notes.append("深层反思未充分触发（8轮内），弹性跳过")
        return {
            "done": done, "c1": c1, "c2": c2, "c3": c3, "c4": c4,
            "c4_skipped": c4_skipped, "reached_cap": reached_cap,
            "notes": "; ".join(notes),
        }

    # ---------- 画像确认 ----------

    def handle_confirmation(self, reply: str) -> dict:
        """处理确认环节的用户回复。返回 {'text': str, 'state': str}。"""
        self._transcript("user", reply)
        accepted = self._is_acceptance(reply)
        if accepted:
            self.session["confirmation"]["response"] = "accepted"
            return self._generate_report()
        self.session["confirmation"]["response"] = "revised"
        self.session["confirmation"]["revision_notes"] = reply
        self.session["status"] = "active"
        self._followups.clear()
        text = (
            "明白了，谢谢你的修正。那我们顺着你说的这一点再聊一会儿，"
            "我看看能不能更好地理解你。"
        )
        self._transcript("assistant", text, {"kind": "revised"})
        self._save()
        return {"text": text, "state": "active"}

    @staticmethod
    def _is_acceptance(reply: str) -> bool:
        r = reply.strip().lower()
        if r.startswith(("y", "yes", "对", "是", "认可", "接近", "差不多", "确实", "嗯")):
            return True
        return False

    # ---------- 报告 ----------

    def _generate_report(self) -> dict:
        self.session["status"] = "completed"
        evidence = evidence_bundle(self.session)
        md = ""
        issues_all = []
        checks = {"ok": False, "issues": []}
        attempts_used = 0
        for attempt in range(3):
            attempts_used = attempt + 1
            feedback = ""
            if issues_all:
                # 带反馈重试：把校验问题反馈给模型，针对性修正
                feedback = "\n".join(f"- {i}" for i in issues_all[:8])
            try:
                md = self.gateway.chat(
                    prompts.REPORT_SYSTEM,
                    prompts.report_prompt(evidence, feedback),
                    model=self.gateway.report_model,
                    temperature=0.6,
                    max_tokens=8000,
                    thinking=True,  # 报告质量优先，思考模式
                )
            except LLMError as e:
                issues_all.append(f"LLM 报告生成失败: {e}")
                continue
            checks = check_report(md, self.session)
            if checks["ok"]:
                break
            issues_all.extend(checks["issues"])

        report_path = self._save_report(md) if md else ""
        self.session["report"] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "path": os.path.relpath(report_path, self.sessions_dir) if report_path else "",
            "checks": {
                "ok": checks["ok"],
                "attempts": attempts_used,
                "issues": issues_all[:10],
                "warnings": checks.get("warnings", [])[:10],
            },
        }
        self._transcript("assistant", "报告已生成。" if md else "报告生成失败。", {"kind": "report_done"})
        self._save()
        if checks["ok"]:
            return {"text": report_path, "state": "completed", "note": "report_generated"}
        return {
            "text": report_path or "",
            "state": "completed",
            "note": "report_generated_with_issues: " + "; ".join(issues_all[:3]) or "report_failed",
        }

    def _save_report(self, md: str) -> str:
        path = os.path.join(self.sessions_dir, self.session["session_id"], "report.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        return path

    # ---------- 工具 ----------

    def _existing_summary(self) -> str:
        lines = []
        for dim in DIMENSIONS:
            summary = anchor_summary(self.session, dim["id"], max_quotes=2)
            if summary != "（尚无）":
                lines.append(f"[{dim['id']} {dim['name']}]\n{summary}")
        contradictions = unresolved_contradictions(self.session)
        if contradictions:
            lines.append(
                "[未解决矛盾]\n" + "\n".join(
                    f"- 「{c['b_quote']}」与「{c['conflicts_with']}」冲突（{c['hint']}）"
                    for c in contradictions
                )
            )
        narratives = self.session["narratives"]
        if narratives:
            lines.append(
                "[叙事事件]\n" + "\n".join(
                    f"- 第{n['round']}轮({n['type']}): {n['story'][:60]}"
                    for n in narratives[-3:]
                )
            )
        if not lines:
            return "（尚无证据）"
        return "\n\n".join(lines)
