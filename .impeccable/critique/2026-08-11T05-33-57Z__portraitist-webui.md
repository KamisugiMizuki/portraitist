---
target: portraitist webui
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 3
timestamp: 2026-08-11T05-33-57Z
slug: portraitist-webui
---
# Portraitist WebUI 设计评审（2026-08-11）

Method: dual-agent (A: 设计审查 · B: detect.mjs 机械检测)
Score: 21/40

## 优点
- 生命周期语义色系统（四态色 + 危机红色徽章，列表/详情贯穿）
- 打开即访谈（新会话自动绑定后端注入欢迎语+开场白）
- 详情页忠实全量展示 transcript（kind 徽章 + 不截断）

## P0
- [x] 详情页命名/日期失真 → 真实 title + created_at（后端补字段）
- [x] 继续访谈上下文断裂 → 标题延续 + 历史注记消息

## P1
- [x] 删除确认不可靠 → showConfirm 带标题 + toast
- [x] 报告校验失败无解释 → warnings 渲染（校验说明区块）
- [x] 0 轮会话堆积 → 事件驱动绑定（点击新建才创建）+ 时序修复

## P2
- [x] 删除按钮 a11y → tabIndex/键盘事件/aria-label/始终可见
- [x] 详情页无 Markdown → 复用 Markdown 组件

## 检测项（B）
- [x] mcp-market.module.scss 残留（AI 味 border-left）→ 删除
- [ ] layout-transition ×2（chat.module.scss width 过渡 / home 0.05s）→ 可选优化，跳过

## 次要观察（未修）
- 术语暴露（维度饱和/未闭环矛盾）需 onboarding 解释
- 状态轮询 30s 延迟
- 127.0.0.1:8000 三处硬编码
- user-select: none 全局禁用复制
- 远程 Google Fonts 请求（中文零收益）
