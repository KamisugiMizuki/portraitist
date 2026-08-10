"""11 个子维度定义（DESIGN.md §5.1）。

每维度属性：
- id: 维度标识（证据库键）
- layer: 所属理论层
- name: 中文名
- desc: 提取器理解该维度内容的说明
- probe: 调度器提问方向提示
- directions: 该维度允许的 direction 标签（用于提取校验）
"""

DIMENSIONS = [
    {
        "id": "trait_energy",
        "layer": "特质层",
        "name": "能量倾向",
        "desc": "外向-内向连续谱：社交中获得或消耗能量，独处时的恢复方式",
        "probe": "社交场合的状态、独处时的恢复方式、主动还是被动发起互动",
        "directions": ["extravert", "introvert", "mixed"],
    },
    {
        "id": "trait_order",
        "layer": "特质层",
        "name": "秩序与随性",
        "desc": "尽责性：计划执行、环境整理、拖延体验、对规则的态度",
        "probe": "计划与临时起意的比例、拖延时的感受、环境混乱的容忍度",
        "directions": ["orderly", "spontaneous", "mixed"],
    },
    {
        "id": "trait_emotion",
        "layer": "特质层",
        "name": "情绪敏感性",
        "desc": "神经质：压力下的情绪波动幅度、情绪恢复速度",
        "probe": "压力事件中的情绪反应、恢复时间、情绪触发点",
        "directions": ["sensitive", "stable", "mixed"],
    },
    {
        "id": "trait_openness",
        "layer": "特质层",
        "name": "认知开放性",
        "desc": "对新事物、不同观点、审美与求知的态度",
        "probe": "面对新事物或对立观点时的第一反应、兴趣广度",
        "directions": ["open", "conventional", "mixed"],
    },
    {
        "id": "trait_agree",
        "layer": "特质层",
        "name": "人际协作风格",
        "desc": "宜人性：合作、竞争、冲突中的角色与让步倾向",
        "probe": "团队合作中的角色、意见分歧时的处理方式",
        "directions": ["cooperative", "assertive", "mixed"],
    },
    {
        "id": "motive_drive",
        "layer": "动机层",
        "name": "主导驱力",
        "desc": "自我决定论：做重要选择时最在意自主、胜任还是归属",
        "probe": "重要选择背后的理由、什么情况下最有动力",
        "directions": ["autonomy", "competence", "relatedness", "mixed"],
    },
    {
        "id": "motive_value",
        "layer": "动机层",
        "name": "价值取向",
        "desc": "自我提升（权力/成就）vs 自我超越（仁爱/普世）的排序",
        "probe": "成功与助人冲突时怎么选、最敬佩什么样的人",
        "directions": ["self_enhancement", "self_transcendence", "mixed"],
    },
    {
        "id": "self_discrepancy",
        "layer": "自我认知层",
        "name": "现实-理想自我距离",
        "desc": "罗杰斯：现实自我与理想自我的距离感及伴随感受",
        "probe": "对现状的评价、理想中的自己、差距带来的感受",
        "directions": ["close", "far", "mixed"],
    },
    {
        "id": "rel_attachment",
        "layer": "关系模式层",
        "name": "依恋策略",
        "desc": "成人依恋：重要关系中的靠近、回避、安全感",
        "probe": "亲密关系中的依赖与独立、分离场景的反应",
        "directions": ["secure", "anxious", "avoidant", "mixed"],
    },
    {
        "id": "rel_defense",
        "layer": "关系模式层",
        "name": "压力第一反应",
        "desc": "冲突或压力瞬间的即时反应：攻击、回避、讨好、理智化等",
        "probe": "冲突瞬间的第一反应、事后是否有不同感受",
        "directions": ["attack", "avoid", "appease", "intellectualize", "mixed"],
    },
    {
        "id": "narrative_identity",
        "layer": "叙事认同层",
        "name": "生命叙事",
        "desc": "麦克亚当斯：人生高潮时刻、转折低潮、关键选择的故事",
        "probe": "请对方讲述一个重要的人生时刻或选择",
        "directions": [],
    },
]

DIMENSION_IDS = [d["id"] for d in DIMENSIONS]
DIRECTIONS_BY_DIM = {d["id"]: d["directions"] for d in DIMENSIONS}
