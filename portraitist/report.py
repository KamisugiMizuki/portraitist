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
    # 诊断术语
    "抑郁症", "抑郁障碍", "焦虑症", "焦虑障碍", "强迫症", "强迫障碍",
    "自恋型人格", "自恋型", "边缘型人格", "偏执型人格", "分裂样",
    "人格障碍", "精神分裂", "双相", "创伤后应激", "PTSD", "躁狂",
    "神经症", "病态", "心理疾病", "心理障碍",
    "进食障碍", "失眠障碍", "惊恐发作", "社交恐惧症", "广场恐惧",
    "躯体化障碍", "解离", "成瘾", "妄想", "幻觉", "躁郁",
    # 类型标签（非诊断但属于贴标签）
    "MBTI", "九型人格", "DISC", "性格色彩", "血型决定", "星座决定",
    "INFP", "INTJ", "ENTP", "ENFP", "INFJ", "ISTJ", "INTP", "ISFJ",
    "ENTJ", "ESTP", "ESFP", "ISTP", "ESTJ", "ESFJ", "ISFP", "ENFJ",
]

# Barnum 式模糊句式模式（注意：'既…又…'是文学性报告的正常修辞，不算 Barnum；
# '你总是X'在有依据时是具体断言，不算 Barnum——由引用校验兜底）
BARNUM_PATTERNS = [
    re.compile(r"有时[^，。；、]{0,15}有时"),
    re.compile(r"时而[^，。；、]{0,15}时而"),
]

# 置信度标注（第 1 段五特质条目应带的标注）
CONFIDENCE_WORDS = ["依据充分", "初步", "推测"]
TRAIT_KEYWORDS = ["开放", "尽责", "外向", "宜人", "神经"]

# 六段结构检查：兼容 "1. " / "## 一、" / "**1. **" 三种标题格式
_TITLE_PREFIX = r"^\s*(?:\*\*|#{1,3}\s*)?(?:[1-6][.、]|[一二三四五六][、.])\s*"
SECTION_PATTERNS = [
    re.compile(_TITLE_PREFIX + r"核心特质图谱", re.M),
    re.compile(_TITLE_PREFIX + r"深层动力引擎", re.M),
    re.compile(_TITLE_PREFIX + r"关系剧本", re.M),
    re.compile(_TITLE_PREFIX + r"生命叙事", re.M),
    re.compile(_TITLE_PREFIX + r"综合(?:真实|自我)?(?:自我)?描述|综合画像|✨", re.M),
    re.compile(_TITLE_PREFIX + r"成长视角", re.M),
    re.compile(r"非诊断声明|不具备临床诊断"),
]
# 与 SECTION_PATTERNS 一一对应的人类可读标签（反馈给模型时用，禁止给正则原文）
SECTION_LABELS = [
    "核心特质图谱", "深层动力引擎", "关系剧本与防御机制", "生命叙事的主线逻辑",
    "综合真实自我描述", "成长视角与盲点", "非诊断声明",
]

CITATION_RE = re.compile(r"依据[：:]\s*轮次?\s*(\d+)")
CITATION_ALT_RE = re.compile(r"〔轮次?\s*(\d+)〕|\[轮\s*(\d+)\]")
# 引用内容片段提取：仅「依据：轮次N·「原话」」规范格式（「」包裹才做内容校验，
# 非规范格式只做轮次存在性检查，避免把后续分析文字卷进捕获导致误报）
CITATION_CONTENT_RE = re.compile(r"依据[：:]\s*轮次?\s*(\d+)\s*[·•,，]\s*「([^」\n\r]{0,80})」")

# 段起始：仅六段主标题（含关键词）或 🧠 头；内部小节标题（如"2. 价值冲突点"）不切段
SECTION_START_RE = re.compile(
    r"^\s*(?:\*\*|#{1,3}\s*)?(?:[1-9][.、]|[一二三四五六七八九十]+[、.])\s*"
    r"(?:核心特质图谱|深层动力引擎|关系剧本|生命叙事|综合|成长视角|真实自我描述|自我描述|画像|✨)"
)


def _quote_matches(quote_fragment: str, round_quotes: list[str]) -> bool:
    """引用片段与证据库原话的宽松匹配（模型可能节选/润色/省略号拼接）。"""
    q = re.sub(r"\s+", "", quote_fragment)
    # 旧格式残留：'原话'/'原话片段'前缀（prompt 格式说明被模型输出）
    q = re.sub(r"^(?:原话片段|原话)", "", q)
    q = q.strip("，。；、！？…「」【】·•,.;:!?~ ")
    if len(q) < 8:
        return True  # 太短无法判断，宽容
    # 省略号拼接：分段匹配（"…"分隔的多个原话片段）
    parts = [p for p in re.split(r"…+|\.{3,}|\.{2,}", q) if len(p) >= 4]
    if len(parts) > 1:
        return all(_quote_matches(p, round_quotes) for p in parts)
    for aq in round_quotes:
        a = re.sub(r"\s+", "", aq)
        if not a:
            continue
        if q in a or a in q:
            return True
        # 前后缀 10 字匹配（应对节选）
        if len(q) >= 12 and (q[:10] in a or q[-10:] in a):
            return True
    return False


def _check_confidence_labels(body: str) -> list[str]:
    """第 1 段五特质条目应带置信度标注（依据充分/初步/推测）。返回缺失项。"""
    missing = []
    for trait in TRAIT_KEYWORDS:
        idx = body.find(trait)
        if idx == -1:
            missing.append(f"{trait}性条目缺失")
            continue
        window = body[idx : idx + 150]
        if not any(w in window for w in CONFIDENCE_WORDS):
            missing.append(f"{trait}性条目缺置信度标注")
    return missing


def check_report(md: str, session: dict) -> dict:
    """校验报告。返回 {'ok': bool, 'issues': [str], 'warnings': [str]}。

    锚点总数 < 6 视为稀疏证据场景（阶段性画像）：引用/结构问题降级为
    warning 不阻塞（模型无证据可引）；正常场景维持严格校验。
    """
    issues = []
    warnings = []
    if not md or len(md.strip()) < 200:
        issues.append("报告过短或为空")
        return {"ok": False, "issues": issues, "warnings": warnings}

    total_anchors = sum(len(d["anchors"]) for d in session.get("dimensions", {}).values())
    sparse = total_anchors < 6
    sections = _split_sections(md)

    def flag(msg: str) -> None:
        if sparse:
            warnings.append(msg)
        else:
            issues.append(msg)

    # 1. 结构检查
    for pat, label in zip(SECTION_PATTERNS, SECTION_LABELS):
        if not pat.search(md):
            flag(f"缺少结构段: {label}")

    # 1b. 置信度标注检查（warning 级，prompt 已要求但不阻塞交付）
    first_section = next((body for title, body in sections
                          if "核心特质图谱" in title), "")
    if first_section:
        warnings.extend(f"置信度: {m}" for m in _check_confidence_labels(first_section))

    # 2. 黑名单（任何场景都严格）
    for term in BLACKLIST_TERMS:
        if term in md:
            issues.append(f"出现诊断术语: {term}")
    for pat in BARNUM_PATTERNS:
        for m in pat.finditer(md):
            issues.append(f"Barnum 式模糊句式: 「{m.group(0)[:30]}」")

    # 3. 引用检查：按六段主标题切段，每段至少 1 处引用（报告头/声明段除外）
    max_round = session.get("rounds", 0)
    round_stats = session.get("round_stats") or []
    for title, body in sections:
        if title == "(报告头)":
            continue
        citations = CITATION_RE.findall(body) + [x or y for x, y in CITATION_ALT_RE.findall(body)]
        if not citations:
            # 合理推测段（显式标注"推测"）允许无引用；未标注的缺引用段打回
            if "推测" in body:
                continue
            # 结构性缺素材：第 4 段（生命叙事）在无叙事素材时无法引用，降级 warning
            if "生命叙事" in title and not session.get("narratives"):
                warnings.append(f"叙事素材不足，{title} 为推测性内容")
                continue
            # 第 5 段（综合描述）是文学总结段，无引用降级 warning（黑名单仍兜底）
            if "综合" in title or "自我描述" in title:
                warnings.append(f"{title} 无引用（综合总结段）")
                continue
            # 总结/建议类段落（4/6 段）内容充分（≥120字）时降级 warning；
            # 内容单薄仍打回（防泛泛建议）
            if ("生命叙事" in title or "成长视角" in title) and len(body) >= 120:
                warnings.append(f"{title} 无引用但内容充分")
                continue
            flag(f"段落无引用: {title}")
            continue
        for c in citations:
            try:
                r = int(c)
            except ValueError:
                flag(f"引用轮次非法: {c}")
                continue
            if r < 1 or r > max_round:
                flag(f"引用轮次越界(>第{max_round}轮): 第{r}轮 @ {title}")
                continue
            # 引用轮次必须有锚点产出，否则疑似编造（空证据幻觉防护）
            if round_stats:
                entry = next((w for w in round_stats if w.get("round") == r), None)
                if entry is None or entry.get("new_anchors", 0) <= 0:
                    flag(f"引用轮次{r}无锚点产出（疑似编造）: @ {title}")
                    continue
                # 引用内容真实性：·后的片段应与该轮证据原话匹配（锚点/反思/叙事）
                round_quotes = [
                    a.get("quote", "") for d in session.get("dimensions", {}).values()
                    for a in d.get("anchors", []) if a.get("round") == r
                ]
                if session.get("reflection", {}).get("round") == r:
                    round_quotes.append(session["reflection"].get("quote", ""))
                round_quotes.extend(
                    n.get("story", "") for n in session.get("narratives", [])
                    if n.get("round") == r
                )
                for m in CITATION_CONTENT_RE.finditer(body):
                    if int(m.group(1)) != r:
                        continue
                    frag = m.group(2)
                    if frag and not _quote_matches(frag, round_quotes):
                        flag(f"引用内容与证据不符（疑似编造）: 「{frag[:30]}」@ {title}")
                        break

    # 4. 证据总量备注
    if total_anchors < 4:
        warnings.append(f"证据稀疏（锚点总数={total_anchors}），报告依据严重不足")

    return {"ok": not issues, "issues": issues, "warnings": warnings}


def _split_sections(md: str) -> list[tuple[str, str]]:
    """按标题切分报告段落（兼容数字/中文数字/markdown 标题），返回 [(标题, 正文)]。"""
    lines = md.splitlines()
    sections = []
    current_title = "(报告头)"
    current_body = []
    for line in lines:
        if SECTION_START_RE.match(line) or line.startswith("🧠"):
            if current_body:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line.strip()[:30]
            current_body = [line]
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_title, "\n".join(current_body)))
    return sections
