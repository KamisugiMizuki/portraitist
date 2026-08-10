#!/usr/bin/env python
"""报告质量统计工具 — M2 验收（DESIGN.md §7.2）。

遍历 sessions/ 下所有 completed 会话，输出：
- 报告校验通过率（引用覆盖率 / 黑名单 / 六段齐全）
- 矛盾闭环率
- 轮次分布与维度覆盖
- 置信度标注缺失

用法：
  .venv/Scripts/python.exe scripts/report_quality.py [--json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from portraitist.dimensions import DIMENSIONS
from portraitist.evidence import load_session
from portraitist.report import check_report, _split_sections, CITATION_RE, CITATION_ALT_RE


def analyze_session(sid: str) -> dict:
    s = load_session(sid, os.path.join(ROOT, "sessions"))
    result = {
        "session_id": sid,
        "status": s.get("status"),
        "rounds": s.get("rounds", 0),
        "anchors": sum(len(d["anchors"]) for d in s["dimensions"].values()),
        "saturated_dims": sum(1 for d in s["dimensions"].values() if d["saturated"]),
        "contradictions_total": len(s["contradictions"]),
        "contradictions_resolved": sum(1 for c in s["contradictions"] if c["resolved"]),
        "report_ok": None,
        "report_attempts": None,
        "citation_ratio": None,
        "sections_found": None,
        "blacklist_hits": 0,
        "confidence_missing": 0,
        "issues": [],
        "warnings": [],
    }
    if s.get("status") != "completed":
        return result

    checks = s.get("report", {}).get("checks", {})
    result["report_ok"] = bool(checks.get("ok"))
    result["report_attempts"] = checks.get("attempts")
    report_path = os.path.join(ROOT, "sessions", sid, "report.md")
    if not os.path.exists(report_path):
        result["issues"] = ["报告文件缺失"]
        return result
    md = open(report_path, encoding="utf-8").read()

    # 重新跑一遍校验（以当前校验器为准，与落盘 checks 独立）
    fresh = check_report(md, s)
    result["report_ok"] = fresh["ok"]
    result["issues"] = fresh["issues"]
    result["warnings"] = fresh["warnings"]
    result["confidence_missing"] = sum(1 for w in fresh["warnings"] if w.startswith("置信度"))
    result["blacklist_hits"] = sum(
        1 for i in fresh["issues"] if "诊断术语" in i or "Barnum" in i
    )

    # 引用覆盖率：有引用的段落 / 非报告头段落
    sections = _split_sections(md)
    body_sections = [t for t, b in sections if t != "(报告头)"]
    cited = 0
    for title, body in sections:
        if title == "(报告头)":
            continue
        if CITATION_RE.search(body) or CITATION_ALT_RE.search(body):
            cited += 1
        elif "推测" in body:
            cited += 1  # 推测段视为有依据降级
    result["citation_ratio"] = (cited / len(body_sections)) if body_sections else None
    result["sections_found"] = len(body_sections)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sessions_dir = os.path.join(ROOT, "sessions")
    results = []
    for ev in sorted(glob.glob(os.path.join(sessions_dir, "*", "evidence.json"))):
        sid = os.path.basename(os.path.dirname(ev))
        results.append(analyze_session(sid))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return

    completed = [r for r in results if r["status"] == "completed"]
    print(f"会话总数: {len(results)} | completed: {len(completed)}\n")

    if not completed:
        return

    ok = [r for r in completed if r["report_ok"]]
    print(f"报告校验通过率: {len(ok)}/{len(completed)}")
    ratios = [r["citation_ratio"] for r in completed if r["citation_ratio"] is not None]
    per = [f"{r['citation_ratio']*100:.0f}%" if r["citation_ratio"] is not None else "n/a"
           for r in completed]
    if ratios:
        print(f"引用覆盖率(段落级): 平均 {sum(ratios)/len(ratios)*100:.0f}% (每会话: {', '.join(per)})")
    else:
        print("引用覆盖率(段落级): n/a")
    print(f"矛盾闭环率: ", end="")
    totals = sum(r["contradictions_total"] for r in completed)
    resolved = sum(r["contradictions_resolved"] for r in completed)
    print(f"{resolved}/{totals}" if totals else "0/0 (无矛盾)")
    rounds_list = [r["rounds"] for r in completed]
    print(f"轮次分布: {rounds_list} | 12轮截断: {sum(1 for r in rounds_list if r >= 12)}/{len(rounds_list)}")
    dims_list = [f"{r['saturated_dims']}/11" for r in completed]
    print(f"维度饱和: {dims_list}")
    print(f"黑名单命中合计: {sum(r['blacklist_hits'] for r in completed)}")
    print(f"置信度标注缺失(会话级): {[r['confidence_missing'] for r in completed]}")

    print("\n── 失败详情 ──")
    for r in completed:
        if not r["report_ok"]:
            print(f"[{r['session_id']}] attempts={r['report_attempts']}")
            for i in r["issues"][:5]:
                print(f"    - {i}")


if __name__ == "__main__":
    main()
