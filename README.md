# Portraitist

通过苏格拉底式多轮对话进行性格画像深度分析的个人工具。每次访谈约 8–12 轮，输出一份有证据、有深度、无标签的心理画像报告。

## 产品定位

- 自我觉察工具，**非临床诊断、非职业测评**（报告附非诊断声明）
- 本地运行：FastAPI 后端 + fork 自 NextChat 的聊天 UI
- LLM 后端可切换：远程 API（默认）/ 本地 LM Studio
- 画像证据锚定用户原话与具体事件，报告强制引用校验（防 Barnum 效应）

## 当前状态

**M1 核心引擎已完成（CLI 形态，2026-08-11）**，设计与决策见 [DESIGN.md](DESIGN.md)。

- 心理学研究依据：大五人格、自我决定论、依恋理论、叙事认同、LLM 心理测量学实证
- 架构决策：程序层状态机控制（终止条件确定性判定）、LLM 仅承担提问/提取/报告三职责
- 对话流程源自 [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md)（五维交叉采集 → 终止判定 → 画像确认 → 六段式报告）
- [PORTABLE.md](PORTABLE.md)：便携版引导师 prompt——无法本地构建或手机端使用时，全文复制给任意大模型即可用

## 目录

```
IDEA.md          项目意图
SYSTEM_PROMPT.md 对话引导师角色定义（心理学流程原稿）
PORTABLE.md      便携版 prompt（网页端/手机端直接取用）
DESIGN.md        完整设计方案（研究依据/架构/接口契约/里程碑/验收标准）
cli.py           M1 CLI 入口：python cli.py 开始访谈
portraitist/     引擎包（状态机/证据库/LLM 网关/报告校验）
tests/           单测（终止判定/调度/报告校验/mock 全流程）
scripts/simulate_user.py  模拟用户验收脚本（LLM 扮演受访者跑全流程）
config.example.yaml  配置模板（复制为 config.yaml 填写）
```

## 使用

```bash
uv venv .venv                            # 独立 venv（每个项目单独建，防环境污染）
.venv/Scripts/python.exe -m pip install -r requirements.txt pytest
cp config.example.yaml config.yaml       # 填入 API key，或 backend: local 连 LM Studio
.venv/Scripts/python.exe cli.py          # 开始访谈
.venv/Scripts/python.exe -m pytest tests/            # 运行测试
.venv/Scripts/python.exe scripts/simulate_user.py --template extravert  # 模拟用户验收
```

M1 已完成；后续里程碑：M2 报告质量打磨 → M3 UI（fork NextChat 瘦身）→ M4 隐私/危机边界。
