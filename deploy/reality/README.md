# Reality DB 批量导入管道（2026-09-23）

护城河=数据资产（方案 §48）：Reality DB 从 13 条起步扩量，靠的是文献/厂商官方
规格的批量化归一入库——单条手工 `POST /api/reality/observations` 不支撑量级。

## 数据流

```
厂商 datasheet / 文献            （人工换算，口径显式写进 note——平台不自动换算不编造）
        │
        ▼
observations.jsonl               （externalKey 唯一 = 幂等键）
        │  python3 batch_import.py --file x.jsonl --api-endpoint ... 
        ▼
POST /api/reality/observations/batch    （全批先校验，任一条非法整批 400 不留半批）
        │  ON CONFLICT DO NOTHING
        ▼
GET /api/reality/observations?deviceModel=&metric=   （报告/校准引擎引用）
```

## 用法

```bash
# 推荐 token 方式（bare token 无 Bearer 前缀；或 export ROBOVERIFY_TOKEN 后省略 --token）
python3 deploy/reality/batch_import.py \
  --file deploy/reality/examples/template.jsonl \
  --api-endpoint http://localhost:18090 \
  --token '...'

# 用户名/口令方式：口令走环境变量——--password 会留在 shell history 与 ps 进程列表里
export ROBOVERIFY_PASSWORD='...'
python3 deploy/reality/batch_import.py \
  --file deploy/reality/examples/template.jsonl \
  --api-endpoint http://localhost:18090 --username admin
```

- 退出码：0 成功；2 文件被拒（HTTP 4xx——看 stderr 里的响应，改文件）；3 网络/
  服务端错误（不可达或 HTTP 5xx——可重试，批量是事务性的不会半批落库）。
- **幂等**：同文件重放 → `created=0 skipped=N`（external_key 部分唯一索引）。
- 上限 1000 条/批，超出分批。
- 模板：`examples/template.jsonl`（占位值，必须替换后使用）。

## 诚实边界（录入纪律）

- `provenance=literature`：数值=官方口径换算的**上界**，note 必须写明原始规格
  （如 `<2% @ 2m`）、换算口径与来源 URL；`derived upper bound, not measured
  distribution` 显式声明。
- `calibrated` 级**不可**经此导入（只由校准 ACTIVE 回写产生，控制器拒绝）。
- `environment` 条件尽量结构化（distance_mm/lux/surface…），供查询面过滤。

## 回滚

误导入按 externalKey 定向清理：

```sql
DELETE FROM reality_observation WHERE external_key LIKE 'datasheet-badbatch-%';
```

批内键约定带来源前缀（datasheet-/bench-/paper-…），清理粒度=按前缀。
