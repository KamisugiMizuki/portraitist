#!/usr/bin/env python
"""重生成全部 completed 会话的报告（校验器/prompt 升级后使用）。

用法：
  .venv/Scripts/python.exe scripts/regenerate_reports.py [--session <id>]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml

from portraitist.engine import Engine
from portraitist.evidence import load_session
from portraitist.llm import LLMGateway


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="只重生成指定会话")
    args = ap.parse_args()

    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    gateway = LLMGateway(cfg)

    targets = []
    for ev in sorted(glob.glob(os.path.join(ROOT, "sessions", "*", "evidence.json"))):
        s = json.load(open(ev, encoding="utf-8"))
        if s.get("status") == "completed":
            targets.append(s["session_id"])
    if args.session:
        targets = [t for t in targets if t == args.session]

    ok = 0
    for sid in targets:
        s = load_session(sid, os.path.join(ROOT, "sessions"))
        s["status"] = "confirming"
        s["report"] = {"generated_at": "", "path": "", "checks": {}}
        engine = Engine(s, gateway, cfg, os.path.join(ROOT, "sessions"))
        try:
            result = engine.handle_confirmation("认可")
        except Exception as e:  # noqa: BLE001 — 单个会话失败不中断批量
            print(f"[{sid}] 异常: {e}")
            continue
        checks = s["report"]["checks"]
        mark = "PASS" if checks.get("ok") else "FAIL"
        if checks.get("ok"):
            ok += 1
        print(f"[{sid}] {mark} attempts={checks.get('attempts')} "
              f"{'; '.join(checks.get('issues', [])[:2])}")

    print(f"\n汇总: {ok}/{len(targets)} 通过")


if __name__ == "__main__":
    main()
