#!/usr/bin/env python
"""Portraitist CLI — M1 引擎验证入口（DESIGN.md M1：核心引擎 CLI 先行）。

用法：
  python cli.py            # 新访谈
  python cli.py <session_id>   # 恢复历史会话（evidence.json 存在时）

内置命令：
  /status   查看维度覆盖矩阵与终止条件进度
  /quit     退出
"""

from __future__ import annotations

import os
import sys

import yaml

from portraitist.dimensions import DIMENSIONS
from portraitist.engine import CRISIS_REMINDER, Engine
from portraitist.evidence import load_session, new_session
from portraitist.llm import LLMGateway, LLMError

ROOT = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(ROOT, "sessions")


def load_config() -> dict:
    path = os.path.join(ROOT, "config.yaml")
    if not os.path.exists(path):
        print(
            "缺少 config.yaml：\n"
            "  1) 复制 config.example.yaml 为 config.yaml\n"
            "  2) 填入 API key（或 backend: local 连接 LM Studio）\n"
            "  3) 重新运行"
        )
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_status(engine: Engine) -> None:
    s = engine.session
    print("\n── 状态 ─────────────────────────────")
    print(f"会话: {s['session_id']} | 状态: {s['status']} | 轮次: {s['rounds']}")
    for dim in DIMENSIONS:
        info = s["dimensions"][dim["id"]]
        n = len(info["anchors"])
        mark = "✓" if info["saturated"] else "·"
        print(f"  {mark} {dim['name']:<8} ({dim['id']}) 锚点×{n}")
    t = s["termination"]
    print(f"终止: C1={t['c1']} C2={t['c2']} C3={t['c3']} C4={t['c4']} "
          f"C4跳过={t['c4_skipped']} 上限={t['reached_cap']}  {t['notes']}")
    print("──────────────────────────────────────\n")


def main() -> None:
    config = load_config()
    try:
        gateway = LLMGateway(config)
    except LLMError as e:
        print(f"配置错误: {e}")
        sys.exit(1)

    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    if session_id and os.path.exists(os.path.join(SESSIONS_DIR, session_id, "evidence.json")):
        session = load_session(session_id, SESSIONS_DIR)
        print(f"已恢复会话 {session_id}（状态: {session['status']}，轮次: {session['rounds']}）")
    else:
        session = new_session()
        print(f"新会话: {session['session_id']}")

    engine = Engine(session, gateway, config, SESSIONS_DIR)

    print("\n你好，我是你的心理探索伙伴。")
    print("先说说你最近的状态吧，我会顺着你说的慢慢聊。")
    print("没有对错答案，想到什么说什么就好。（/status 可查看进度，/quit 退出）\n")

    if session["rounds"] == 0:
        print("引导师>", engine.first_question())
    else:
        print("（继续上次对话，直接输入你的回复）")

    while True:
        try:
            reply = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n对话已中断，证据已保存，可用 python cli.py "
                  f"{session['session_id']} 恢复。")
            break
        if not reply:
            continue
        if reply in ("/quit", "/exit"):
            print("对话已结束，证据已保存。")
            break
        if reply == "/status":
            print_status(engine)
            continue

        if engine.session["status"] == "confirming":
            result = engine.handle_confirmation(reply)
            print("引导师>", result["text"])
            if result["state"] == "completed":
                if result.get("text"):
                    print(f"\n📄 报告已生成: {result['text']}")
                else:
                    print("\n报告生成失败（见 sessions/ 中 evidence.json 的 checks）。")
                break
            continue

        try:
            result = engine.run_round(reply)
        except LLMError as e:
            print(f"[错误] {e}（可重试输入）")
            continue
        print("引导师>", result["text"])
        if result["note"].startswith("crisis"):
            print(CRISIS_REMINDER)
        if result["state"] == "confirming":
            print("\n（画像轮廓确认：认可请回复『认可』；需要修正请直接说明）\n")


if __name__ == "__main__":
    main()
