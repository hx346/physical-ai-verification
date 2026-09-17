-- V10__failure_backfill.sql — PostgreSQL：存量失败取证回填（V0.9，dev-plan §13 任务 2）
-- 护城河资产抢救：V0.5 W2/W4 已产生的高质量失败取证，原先仅存于 dev-plan 进展
-- 记录与 commit message，现结构化入库。来源=平台自身仿真校准史，project_id 置空
-- （平台级取证库，非客户项目归属）；报告 v3 Failure 章节以"平台库"归属并列呈现。
-- external_key 幂等（V9 部分唯一索引）：迁移重放安全。
INSERT INTO failure_record (project_id, external_key, failure_mode, failure_desc, root_cause,
                            correction, outcome, severity, source, trace, detected_at)
VALUES
(NULL, 'backfill-w4-ground-plane', 'place_launch_bounce',
 '放置释放后零件弹飞 360mm+（六策略矩阵同值 360mm 的确定性指纹=场景级 bug 线索）',
 '地面 plane 实际在 z=-0.01 而释放逻辑按 0 计算——零件悬空 ~10mm 开指，60N 挤压穿透回弹空中击飞。两个不同 seed 同落 x=0.8405 的确定性指纹破案；V0.3 归档的"DART 突释数值特性"归因不完整',
 'placeSurfaceZ 进场景束（地面 -0.01 / 箱内 t+0.01 场景真值）+ _descend_until 低速闭环两段触地 + 全张后对准零件居中再回退',
 '同 seed n=6：拾取 5/6，放置 7.9-40mm（全重量级；重件 360→38.8mm）',
 'critical', 'sim',
 '{"origin": "V0.5 W4", "evidence": "E00113", "method": "六策略探针矩阵+确定性指纹"}'::jsonb,
 '2026-09-16T00:00:00Z'),

(NULL, 'backfill-w4-hardstop-slip', 'transport_slip_hardstop',
 '提升/运输段零件中途滑脱坠落，再被下降夹爪撞飞',
 '位置 _move_to 硬停（0.25→0 m/s 一步 ~25g）向下减速度 > μg=3g，零件中途滑脱',
 '_descend_until 低速闭环两段触地（vz=-0.04/-0.02 按零件实测 z 停止，消除标称依赖与硬停滑脱）',
 '同上批次验证：稳定场景 position_error 5.9-40mm',
 'high', 'sim',
 '{"origin": "V0.5 W4", "evidence": "E00113", "method": "六策略探针矩阵"}'::jsonb,
 '2026-09-16T00:00:00Z'),

(NULL, 'backfill-w4-depressurize-burst', 'grip_release_burst',
 '开指瞬间零件被弹射（小轻件 508mm）',
 '夹持力 60→0 一跳泄压，瞬间释放接触穿透储能（冲量与质量无关；地面摩擦 0.5mg 对 0.1kg 件仅 0.5N 拉不住）',
 '准静态卸载：60→45→…→2→0 渐降',
 '同上批次验证通过',
 'high', 'sim',
 '{"origin": "V0.5 W4", "evidence": "E00113", "method": "力级/泄压时长探针"}'::jsonb,
 '2026-09-16T00:00:00Z'),

(NULL, 'backfill-w2-contact-falsified', 'hypothesis_falsified_contact_loss',
 'V0.3 曾归因"DART 接触失效"（pick_success=0 十五轮）——该假设被证伪',
 '证伪证据：接触检测/响应从未缺失（82 万接触条目、指停零件面 ±0.025、dart/bullet 皆稳）。真因三件：① SDF <inertial> 缺 <inertia> 默认单位阵（大 4 个数量级）→ LCP 病态互踢；② 实心箱零件生成于固体内部=深穿透弹射；③ protobuf 文本省略零值字段致坐标轴位姿漏读',
 '全 link 显式盒惯量 + 五面空心箱 + protobuf 位姿逐轴可选解析',
 '指面 contact sensor 4/4 指标 measured（E00174-E00188）；pick_success 1.0 可复现 3/3',
 'high', 'sim',
 '{"origin": "V0.5 W2", "evidence": "E00174-E00188", "method": "碰撞单变量探针 collision_probe.py"}'::jsonb,
 '2026-09-15T00:00:00Z'),

(NULL, 'backfill-w3-analytic-overestimate', 'analytic_mapping_overestimate',
 '解析式 1:1 映射高估 depth_noise 杠杆（解析 share 0.60 vs 真实链 0.83 排序反转）',
 '解析路径把 depth_noise 直接映射为抓取目标三轴定位噪声；真实感知链下顶视+质心 √N 平均+抓取容差使杠杆臂仅 ~5-13%（帧偏置主导被容差吸收）',
 '敏感性 share 让位 friction/object_size；解析与仿真结论并列呈现，不单独裁决',
 'E00280 n=6 记录；假设清单已入对照实验边界',
 'medium', 'sim',
 '{"origin": "V0.5 W3", "evidence": "E00280", "method": "解析 vs 仿真敏感性并列"}'::jsonb,
 '2026-09-16T00:00:00Z'),

(NULL, 'backfill-w4-mu-slip-baseline', 'transport_slip_low_mu',
 'μ=0.18 滑腻面零件运输段滑脱（确定复现）',
 '真实物理失败：0.5mg 摩擦上限对 0.1kg 件仅 ~0.5N，运输加速度超 μg 即滑——非 bug',
 '不修正——保留为已知失败模式基线（part_mass_kg/friction_coeff override 支持确定性复现）',
 '作为对照基线保留，用于未来 Real2Sim 摩擦参数校准的锚点之一',
 'medium', 'sim',
 '{"origin": "V0.5 W4", "evidence": "E00113", "method": "确定性复现保留"}'::jsonb,
 '2026-09-16T00:00:00Z');
