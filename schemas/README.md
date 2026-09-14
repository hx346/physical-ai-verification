# schemas — Engineering IR（唯一权威契约）

本目录是 Platform（Java）与 Runtime（Python）之间**所有**中间表示的唯一权威定义（JSON Schema draft 2020-12）。两侧模型必须由这些 schema 生成/校验，禁止手写漂移（ADR-0001/0004）。

计划内容（M0 冻结 v0.1）：

```
schemas/
├── ir/
│   ├── requirement.schema.json
│   ├── task.schema.json
│   ├── system.schema.json
│   ├── state.schema.json
│   ├── environment.schema.json
│   ├── experiment.schema.json        # M3 冻结
│   ├── simulation.schema.json        # M2 冻结
│   └── evidence.schema.json
├── openapi/                           # platform ↔ runtime REST 契约
└── examples/                          # 示例文档（兼作双语言校验用例）
```

规则：

- 每个 IR 带 `schemaVersion`（语义化版本）；破坏性变更升主版本并双版本共存过渡。
- 误差参数必须携带 `provenance`：`datasheet | literature | measured | calibrated`（ADR-0004）。
- 变更流程：PR 评审 → 更新 schema + 双语言校验用例 → CI 绿 → 合并；CI 含 schema 校验任务。
