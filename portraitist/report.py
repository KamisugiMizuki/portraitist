"""报告质量校验（DESIGN.md §5.5、§7.2）。

程序层防线：
1. 引用检查——每段分析必须含「依据：轮次N」引用标记，缺引用的段落打回；
2. 黑名单——诊断术语 / Barnum 式模糊句式拦截；
3. 结构检查——六段齐全 + 非诊断声明在位。
"""

from __future__ import annotations

import re

# 诊断/标签术语黑名单（报告禁止出现）
BLACKLIST_TERMS = [
    "抑郁症", "抑郁障碍", "焦虑症", "焦虑障碍", "强迫症", "强迫障碍",
    "自恋型人格", "自恋型", "边缘型人格", "偏执型人格", "分裂样",
    "人格障碍", "精神分裂", "双相", "创伤后应激", "PTSD", "躁狂",
    "神经症", "病态", "心理疾病", "心理障碍",
]

# Barnum 式模糊句式模式
BARNUM_PATTERNS = [
    re.compile(r"有时[^，。；、]{0,15}有时"),
    re.compile(r"时而[^，。；、]{0,15}时而"),
    re.compile(r"既[^，。；、]{0,10}又[^，。；、]{0,10}"),
]

# 六段结构检查：数字标题 + 非诊断声明
SECTION_PATTERNS = [
    re.compile(r"1[.、]\s*核心特质图谱"),
    re.compile(r"2[.、]\s*深层动力引擎"),
    re.compile(r"3[.、]\s*关系剧本"),
    re.compile(r"4[.、]\s*生命叙事"),
    re.compile(r"5[.、]\s*(综合真实自我描述|✨)"),
    re.compile(r"6[.、]\s*成长视角"),
    re.compile(r"非诊断声明|不具备临床诊断"),
]

CITATION_RE = re.compile(r"依据[：:]\s*轮次?\s*(\d+)")
CITATION_ALT_RE = re.compile(r"〔轮次?\s*(\d+)〕|\[轮\s*(\d+)\]")


def check_report(md: str, session: dict) -> dict:
    """校验报告。返回 {'ok': bool, 'issues': [str]}。"""
    issues = []
    if not md or len(md.strip()) < 200:
        issues.append("报告过短或为空")
        return {"ok": False, "issues": issues}

    # 1. 结构检查
    for pat in SECTION_PATTERNS:
        if not pat.search(md):
            issues.append(f"缺少结构段: {pat.pattern}")

    # 2. 黑名单
    for term in BLACKLIST_TERMS:
        if term in md:
            issues.append(f"出现诊断术语: {term}")
    for pat in BARNUM_PATTERNS:
        for m in pat.finditer(md):
            issues.append(f"Barnum 式模糊句式: 「{m.group(0)[:30]}」")

    # 3. 引用检查：按数字标题切段，每段至少 1 处引用（报告头/声明段除外）
    sections = _split_sections(md)
    max_round = session.get("rounds", 0)
    for title, body in sections:
        if title == "(报告头)":
            continue
        citations = CITATION_RE.findall(body) + [x or y for x, y in CITATION_ALT_RE.findall(body)]
        if not citations:
            issues.append(f"段落无引用: {title}")
            continue
        for c in citations:
            try:
                r = int(c)
            except ValueError:
                issues.append(f"引用轮次非法: {c}")
                continue
            if r < 1 or r > max_round:
                issues.append(f"引用轮次越界(>第{max_round}轮): 第{r}轮 @ {title}")

    return {"ok": not issues, "issues": issues}


def _split_sections(md: str) -> list[tuple[str, str]]:
    """按数字标题切分报告段落，返回 [(标题, 正文)]。"""
    lines = md.splitlines()
    sections = []
    current_title = "(报告头)"
    current_body = []
    for line in lines:
        if re.match(r"^\s*\d+[.、]\s*\S", line) or line.startswith("🧠"):
            if current_body:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line.strip()[:30]
            current_body = [line]
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_title, "\n".join(current_body)))
    return sections
