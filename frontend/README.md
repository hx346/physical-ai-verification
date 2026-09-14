# frontend — Web UI（Vue 3）

Vue 3 · TypeScript · Vite · Ant Design Vue · Pinia · ECharts。

核心页面优先级（V0.1，见产品方案 §38/§39）：

1. **Verification Matrix**（hero 页）：需求 × 指标 × 现值 × 要求 × 判定 × 证据下钻
2. Requirement / System Design / Asset Configuration
3. Simulation Run / Experiment / Sensitivity（M2/M3）
4. Evidence / Report

明确不做（V0.1）：3D 编辑器、复杂大屏。
API 类型从 backend 的 OpenAPI 生成（M0 起接入代码生成器，禁止手写漂移）。
