#!/usr/bin/env python
"""模拟用户脚本 — M1 验收：LLM 扮演受访者跑完整访谈流程（DESIGN.md §7.1）。

用法：
  python scripts/simulate_user.py --template extravert --iterations 2

人格模板：extravert / introvert / contradictory / terse
输出：每轮对话摘要 + 终止条件 + 报告校验结果。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from portraitist.engine import Engine
from portraitist.evidence import new_session
from portraitist.llm import LLMGateway, LLMError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")

TEMPLATES = {
    "extravert": {
        "role": "一个热情外向的人，能量来自人群，喜欢组织和参与社交，工作中主动牵头",
        "extra": "具体、鲜活，带场景细节",
    },
    "introvert": {
        "role": "一个内向的人，享受独处，社交后需要长时间恢复，工作专注但回避聚会",
        "extra": "具体、鲜活，带场景细节",
    },
    "contradictory": {
        "role": "一个表面随和但内心抗拒权威的人：喜欢独处却极度害怕被团队边缘化",
        "extra": "平时说话常带内在张力（如'想去又怕麻烦''嘴上答应心里抗拒'），显得自然；但当对方直接追问你某两句话为何矛盾时，会认真解释两面如何共存（如'其实不冲突，因为……'），给出整合性的回答",
    },
    "terse": {
        "role": "一个话少的人，回答简短抽象（如\"还行\"\"看情况\"\"一般吧\"），偶尔在追问下才说细节",
        "extra": "大多数回答不超过10个字；被追问具体场景时才展开一两句",
    },
}

USER_SYSTEM = (
    "你正在参与一次心理访谈。你是受访者，扮演的角色是：{role}。\n"
    "规则：\n"
    "1. 用第一人称回答，讲具体的生活经历和场景；{extra}\n"
    "2. 语气自然口语化，绝不提\"维度\"\"分析\"\"访谈\"\"评估\"等字眼；\n"
    "3. 不要反问，不要总结自己，只回答对方的问题。"
)


def load_config() -> dict:
    path = os.path.join(ROOT, "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_one(config: dict, template: str, iteration: int) -> dict:
    gateway = LLMGateway(config)
    session = new_session()
    engine = Engine(session, gateway, config, SESSIONS_DIR)

    print(f"\n===== 模拟 {template} 第 {iteration} 次 =====")
    user_system = USER_SYSTEM.format(**TEMPLATES[template])

    q = engine.first_question()
    print(f"[引导师] {q[:80]}")
    rounds = 0
    while True:
        try:
            reply = gateway.chat(
                user_system, f"对方问：{q}\n\n请以受访者身份回答。",
                temperature=0.9, max_tokens=300, thinking=False,
            )
        except LLMError as e:
            print(f"[用户扮演失败] {e}")
            return {"rounds": rounds, "error": str(e)}
        print(f"[用户] {reply[:100]}")
        result = engine.run_round(reply)
        rounds = engine.session["rounds"]
        q = result["text"]
        if result["state"] == "confirming":
            print(f"[引导师·确认] {q[:80]}")
            final = engine.handle_confirmation("认可")
            print(f"[完成] 状态={final['state']} 报告={final.get('text')}")
            return {
                "rounds": rounds,
                "status": final["state"],
                "termination": engine.session["termination"],
                "report_ok": engine.session["report"]["checks"].get("ok"),
                "report_issues": engine.session["report"]["checks"].get("issues", [])[:5],
            }
        # 循环保护：上限 = 访谈轮数上限 + 强制澄清宽容轮数
        guard = engine.max_rounds + engine.max_clarify_rounds
        if rounds >= guard:
            print(f"[异常] 超过 {guard} 轮仍未结束")
            return {"rounds": rounds, "error": "loop_guard"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", choices=list(TEMPLATES), default="extravert")
    ap.add_argument("--iterations", type=int, default=2)
    args = ap.parse_args()

    config = load_config()
    results = []
    for i in range(1, args.iterations + 1):
        r = run_one(config, args.template, i)
        results.append(r)
        if r.get("error"):
            continue
        t = r["termination"]
        print(
            f"  → {r['rounds']} 轮 | C1={t['c1']} C2={t['c2']} C3={t['c3']} C4={t['c4']} "
            f"| 报告校验={'PASS' if r['report_ok'] else 'FAIL: ' + '; '.join(r['report_issues'])}"
        )

    ok = [r for r in results if r.get("status") == "completed" and r.get("report_ok")]
    print(f"\n===== 汇总: {len(ok)}/{len(results)} 全流程通过 =====")
    sys.exit(0 if ok and len(ok) == len(results) else 1)


if __name__ == "__main__":
    main()
