"""Verification Kernel — 判定只能来自公式/求解器/蒙特卡洛，绝不来自 LLM（原则二）。

模块：
- snapshot     系统+资产 → 计算快照（含 provenance 追踪）
- models_v01   显式模型系数（版本化，禁止散落魔法值）
- constraint   规则类判定（reach/payload/FOV）
- uncertainty  RSS + Monte Carlo（P50/P90/P95 + bootstrap CI + 贡献度）
- timing       端到端时延预算
- observability 状态需求 vs 传感器能力
- success      抓取成功率概率模型（供 verify 与实验引擎共用）
- registry     指标分发与需求判定入口
"""

KERNEL_VERSION = "0.1.0"
