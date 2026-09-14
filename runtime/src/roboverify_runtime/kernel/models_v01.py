"""显式模型系数（v0.1）——全部魔法值集中于此并版本化，供回滚与校准对照。

重要：这些系数是**未校准的工程假设**（provenance 见各常量注释），
M4 Real2Sim 校准后生成 model_version 新版本替换，历史证据仍绑定本版本。
"""

# —— 位置精度模型 ——
# 单目深度经已知尺寸位姿估计的相对误差（典型文献量级 0.3%~1%，取中值）
MONOCULAR_DEPTH_SIGMA_RATIO = 0.005  # 1σ / 距离，provenance: literature
# 深度误差随距离线性外推：sigma(d) = sigma_ref * (d / d_ref)
DEPTH_SIGMA_DISTANCE_EXPONENT = 1.0  # 线性，provenance: datasheet 内插假设

# —— 节拍模型 ——
MOVE_SEGMENTS = 3  # approach / transfer / retreat
SEGMENT_CLEARANCE_M = 0.15  # 每段路径附加安全距离
ROBOT_BASE_OFFSET_M = 0.25  # 机器人基座到料箱中心的水平偏移（安装假设）
GRASP_CLOSE_TIME_S = 0.30  # 夹爪闭合时间（无速度参数时的假设）
INFERENCE_LATENCY_MS_DEFAULT = 40.0  # 感知推理时延假设
PLANNING_LATENCY_MS_DEFAULT = 35.0   # 运动规划时延假设
PERCEPTION_OVERHEAD_S = 0.10         # 触发/同步开销假设

# —— 抓取成功率模型（logistic）——
# success = sigmoid(A - B*occlusion - C*sigma_eff / SIZE_NORM * object_size_norm)
SUCCESS_MODEL_VERSION = "success-model-v0.1-draft"
SUCCESS_A = 8.8   # 基线（理想条件成功率极高），uncalibrated
SUCCESS_B = 4.0   # 遮挡惩罚系数（0~1 遮挡率），uncalibrated
SUCCESS_C = 1.8   # 有效定位误差惩罚系数（mm），uncalibrated
OBJECT_SIZE_NORM_MM = 50.0  # 尺寸归一化基准（大零件容错更高）

# —— 蒙特卡洛 ——
MONTE_CARLO_N_DEFAULT = 10_000
BOOTSTRAP_N = 1_000
CI_LEVEL = 0.95
