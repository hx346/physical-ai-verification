-- V2__seed.sql — PostgreSQL 17（方言：PostgreSQL）
-- 幂等：重复执行无副作用（ON CONFLICT DO NOTHING）
-- 默认管理员：admin / roboverify123（PBKDF2-SHA256, 120k 迭代；生产环境必须改密）

INSERT INTO auth_user (username, password_hash, role, display_name)
VALUES ('admin', 'pbkdf2:726f626f766572696679:29f0820a887c69e7e2c8e944d73e43f905c494c987feaf6d128d3c59ba1ef291', 'admin', 'Administrator')
ON CONFLICT (username) DO NOTHING;

-- 种子资产（与 schemas/examples/asset/seed.yaml 同源；全部 provenance=datasheet 占位，ADR-0004）
INSERT INTO asset (id, category, vendor, model, cost_cny, ir) VALUES
('asset-robot-a', 'robot', 'SEED-PLACEHOLDER', '6R-900 通用六轴', 85000,
 '{"schemaVersion":"0.1.0","id":"asset-robot-a","category":"robot","vendor":"SEED-PLACEHOLDER","model":"6R-900 通用六轴","cost_cny":85000,"params":[
   {"name":"dof","value":6,"provenance":"datasheet"},
   {"name":"reach_mm","value":900,"provenance":"datasheet"},
   {"name":"payload_kg","value":5,"provenance":"datasheet"},
   {"name":"repeatability_mm","value":0.03,"provenance":"datasheet"},
   {"name":"absolute_accuracy_mm","value":0.5,"provenance":"datasheet","note":"厂商宣称值，偏乐观"},
   {"name":"max_tcp_speed_mm_s","value":1000,"provenance":"datasheet"},
   {"name":"controller_latency_ms","value":11,"provenance":"datasheet"}]}'::jsonb),
('asset-robot-b', 'robot', 'SEED-PLACEHOLDER', '6R-1100 长臂六轴', 110000,
 '{"schemaVersion":"0.1.0","id":"asset-robot-b","category":"robot","vendor":"SEED-PLACEHOLDER","model":"6R-1100 长臂六轴","cost_cny":110000,"params":[
   {"name":"dof","value":6,"provenance":"datasheet"},
   {"name":"reach_mm","value":1100,"provenance":"datasheet"},
   {"name":"payload_kg","value":10,"provenance":"datasheet"},
   {"name":"repeatability_mm","value":0.05,"provenance":"datasheet"},
   {"name":"absolute_accuracy_mm","value":0.8,"provenance":"datasheet"},
   {"name":"max_tcp_speed_mm_s","value":1200,"provenance":"datasheet"},
   {"name":"controller_latency_ms","value":12,"provenance":"datasheet"}]}'::jsonb),
('asset-robot-c', 'robot', 'SEED-PLACEHOLDER', '6R-850 紧凑六轴', 68000,
 '{"schemaVersion":"0.1.0","id":"asset-robot-c","category":"robot","vendor":"SEED-PLACEHOLDER","model":"6R-850 紧凑六轴","cost_cny":68000,"params":[
   {"name":"dof","value":6,"provenance":"datasheet"},
   {"name":"reach_mm","value":850,"provenance":"datasheet"},
   {"name":"payload_kg","value":4,"provenance":"datasheet"},
   {"name":"repeatability_mm","value":0.02,"provenance":"datasheet"},
   {"name":"absolute_accuracy_mm","value":0.4,"provenance":"datasheet"},
   {"name":"max_tcp_speed_mm_s","value":900,"provenance":"datasheet"},
   {"name":"controller_latency_ms","value":10,"provenance":"datasheet"}]}'::jsonb),
('asset-rgb-cam-b', 'camera', 'SEED-PLACEHOLDER', 'RGB-5MP-GigE 面阵相机', 4500,
 '{"schemaVersion":"0.1.0","id":"asset-rgb-cam-b","category":"camera","vendor":"SEED-PLACEHOLDER","model":"RGB-5MP-GigE 面阵相机","cost_cny":4500,"params":[
   {"name":"resolution","value":"2448x2048","provenance":"datasheet"},
   {"name":"fps","value":30,"provenance":"datasheet"},
   {"name":"fov_deg","value":60,"provenance":"datasheet"},
   {"name":"interface","value":"GigE","provenance":"datasheet"},
   {"name":"latency_ms","value":18,"provenance":"datasheet"},
   {"name":"depth_available","value":false,"provenance":"datasheet","note":"单目 2D，无度量深度"}]}'::jsonb),
('asset-rgbd-cam-c', 'camera', 'SEED-PLACEHOLDER', 'RGB-D 深度相机 C', 8500,
 '{"schemaVersion":"0.1.0","id":"asset-rgbd-cam-c","category":"camera","vendor":"SEED-PLACEHOLDER","model":"RGB-D 深度相机 C","cost_cny":8500,"params":[
   {"name":"resolution","value":"1280x720","provenance":"datasheet"},
   {"name":"fps","value":30,"provenance":"datasheet"},
   {"name":"fov_deg","value":87,"provenance":"datasheet"},
   {"name":"range_mm","value":{"min":300,"max":3000},"provenance":"datasheet"},
   {"name":"interface","value":"USB3","provenance":"datasheet"},
   {"name":"latency_ms","value":22,"provenance":"datasheet"},
   {"name":"depth_available","value":true,"provenance":"datasheet"},
   {"name":"depth_sigma_mm","value":1.2,"unit":"mm","provenance":"datasheet","conditions":{"distance_mm":700,"surface":"semi"},"note":"手册标称 1σ，反射金属表面实际偏差更大"}]}'::jsonb),
('asset-rgbd-cam-d', 'camera', 'SEED-PLACEHOLDER', 'RGB-D 深度相机 D（高精度型）', 26000,
 '{"schemaVersion":"0.1.0","id":"asset-rgbd-cam-d","category":"camera","vendor":"SEED-PLACEHOLDER","model":"RGB-D 深度相机 D（高精度型）","cost_cny":26000,"params":[
   {"name":"resolution","value":"1280x1024","provenance":"datasheet"},
   {"name":"fps","value":60,"provenance":"datasheet"},
   {"name":"fov_deg","value":70,"provenance":"datasheet"},
   {"name":"range_mm","value":{"min":200,"max":2000},"provenance":"datasheet"},
   {"name":"interface","value":"GigE","provenance":"datasheet"},
   {"name":"latency_ms","value":15,"provenance":"datasheet"},
   {"name":"depth_available","value":true,"provenance":"datasheet"},
   {"name":"depth_sigma_mm","value":0.4,"unit":"mm","provenance":"datasheet","conditions":{"distance_mm":700,"surface":"semi"}}]}'::jsonb),
('asset-gripper-b', 'gripper', 'SEED-PLACEHOLDER', '2 指平行夹爪 B', 12000,
 '{"schemaVersion":"0.1.0","id":"asset-gripper-b","category":"gripper","vendor":"SEED-PLACEHOLDER","model":"2 指平行夹爪 B","cost_cny":12000,"params":[
   {"name":"grip_force_n","value":80,"provenance":"datasheet"},
   {"name":"stroke_mm","value":60,"provenance":"datasheet"},
   {"name":"control_latency_ms","value":15,"provenance":"datasheet"},
   {"name":"repeatability_mm","value":0.05,"provenance":"datasheet"},
   {"name":"feedback","value":"position+force","provenance":"datasheet"}]}'::jsonb),
('asset-gripper-h', 'gripper', 'SEED-PLACEHOLDER', '真空吸盘 H', 6000,
 '{"schemaVersion":"0.1.0","id":"asset-gripper-h","category":"gripper","vendor":"SEED-PLACEHOLDER","model":"真空吸盘 H","cost_cny":6000,"params":[
   {"name":"type","value":"vacuum","provenance":"datasheet"},
   {"name":"payload_kg","value":2,"provenance":"datasheet","note":"仅适用于平整表面"},
   {"name":"control_latency_ms","value":30,"provenance":"datasheet"},
   {"name":"feedback","value":"none","provenance":"datasheet"}]}'::jsonb)
ON CONFLICT (id) DO NOTHING;
