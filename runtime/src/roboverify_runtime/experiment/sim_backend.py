"""backend=simulator 实验引擎（V0.3 W4）：LHS 采样 → N 次 headless gz → 聚合 + 一阶敏感性。

V0.5 W1 起生产路径为 DAG（worker/handlers/experiment.py）：父任务采样后展开
N 个 simulation 子 job 并行执行、轮询收割后调 aggregate_runs——本模块的
run_simulation_experiment 串行路径保留为参考实现，noise_instance/
build_run_sim_ir/aggregate_runs 为两条路径共享（逐位一致可复现）。

参数映射（显式可审，未映射参数如实标注，不猜）：
- depth_noise_mm → V0.5 W3 感知链：模板 perception.enabled 时进深度帧噪声
  （帧偏置 N(0,σ) 主导 + 逐像素 iid σ/10 次要 → 反投影质心 → 控制目标）；
  无感知模板时回退 W4 语义：N(0, σ) 三轴独立偏移直接注入抓取目标。
  判定（pick_success/position_error/perception_error）始终用零件真实位姿
- object_size_mm → 场景零件尺寸（scene_builder overrides，单件箱）
- friction_coeff → 零件表面摩擦 μ（scene_builder overrides）
- illumination_lux / occlusion_percent / network_latency_ms → 未映射：
  脚本化抓取无感知闭环（相机不参与控制链），映射属 V0.4 感知规划

敏感性方法：SRC（Pearson r²，标准化回归系数平方）。Saltelli-Sobol 需
N×(2k+2) 次仿真求值（6 参数 base N=256 → 3584 次 ≈ 60h），单工作站不可行
（dev-plan W4 耗时假设的实测结论）；LHS 样本上 SRC 与一阶 Sobol 在单调
响应下排序一致。样本量与 R²（多元线性模型方差解释比）随结果显式标注。
"""

from __future__ import annotations

import copy
import random
import time
from collections.abc import Callable

import numpy as np

from ..logging_setup import get_logger
from ..sim_adapters import get_adapter
from .sampling import sample

log = get_logger("experiment.sim_backend")

AGG_METRICS = ("pick_success", "cycle_time_s", "position_error_mm", "collision_count",
                  "perception_error_mm")  # perception_error_mm：W3 真实感知链定位误差

NOISE_STREAM_OFFSET = 7919  # 定位噪声流与场景 seed 解耦的固定偏移


def noise_instance(seed: int, i: int, sigma_m: float) -> tuple[float, float, float]:
    """第 i run 的定位噪声实例（三轴独立，各向同性近似）。

    与串行路径同流可复现：random.Random(seed+7919) 的 gauss 调用序列中，
    uniform 消耗只与调用次数相关（与 σ 无关）——跳过前 3i 次调用即得第 i 组。
    """
    rng = random.Random(seed + NOISE_STREAM_OFFSET)
    for _ in range(3 * i):
        rng.gauss(0.0, 1.0)
    return tuple(round(rng.gauss(0.0, sigma_m), 4) for _ in range(3))


def build_run_sim_ir(template: dict, row: dict, i: int, seed: int) -> dict:
    """第 i run 的仿真 IR：模板 + 已采样参数实例（尺寸/摩擦/感知噪声）+ 独立场景 seed。

    串行引擎与 DAG 子任务共用（参数映射注释见模块头），保证两条路径逐位一致。
    V0.5 W3：模板 perception.enabled 时 depth_noise_mm → 感知链真实噪声
    （帧偏置+逐像素，见 perception/depth_localize.py）；否则保持 W4 注入路径。
    """
    sim_ir = copy.deepcopy(template)
    env = sim_ir.setdefault("environment", {})
    # 每次运行独立场景随机化（零件位姿/质量）——同参数不同实现，实验随机性来源
    env["seed"] = int(env.get("seed", 42)) + i
    overrides = env.setdefault("overrides", {})
    overrides.setdefault("n_parts", 1)
    if "object_size_mm" in row:
        overrides["object_size_mm"] = round(row["object_size_mm"], 2)
    if "friction_coeff" in row:
        overrides["friction_coeff"] = round(row["friction_coeff"], 3)
    if (template.get("perception") or {}).get("enabled"):
        # W3：深度噪声进真实感知链（定位误差→控制目标→真实物理成败）
        p = sim_ir.setdefault("perception", {})
        p["enabled"] = True
        p["topic"] = template["perception"].get("topic", "/camera/rgbd/depth_image")
        p["depth_noise_mm"] = round(row.get("depth_noise_mm", 0.0), 2)
        p["rng_seed"] = seed * 1000 + i * 31 + 7
    else:
        # W4：depth_noise → 已采样的定位误差实例直接注入控制目标
        sigma_m = row.get("depth_noise_mm", 0.0) / 1000.0
        overrides["graspNoiseXYZ"] = list(noise_instance(seed, i, sigma_m))
    return sim_ir


def run_simulation_experiment(experiment: dict,
                              progress_cb: Callable[[int, int], None] | None = None) -> dict:
    """完整仿真实验：采样 → 逐 run headless gz → 聚合 + 敏感性。

    progress_cb(done, total)：每 run 完成后回调（进度可见性；回调异常由
    调用方负责吞掉，不得影响实验本体）。
    """
    params = experiment["parameters"]
    sampling = experiment["sampling"]
    n = int(sampling["n"])
    seed = int(sampling.get("seed", 20260914))
    template = experiment.get("simulation") or {}
    if not template:
        raise ValueError("backend=simulator 实验缺少 simulation 模板")

    X, names = sample(params, sampling.get("method", "lhs"), n, seed)
    adapter = get_adapter("gz")

    runs: list[dict] = []
    t_batch = time.monotonic()
    for i in range(n):
        row = {k: float(v) for k, v in zip(names, X[i], strict=False)}
        sim_ir = build_run_sim_ir(template, row, i, seed)
        noise = sim_ir["environment"]["overrides"].get("graspNoiseXYZ", (0, 0, 0))

        t0 = time.monotonic()
        run_rec = {"i": i, "params": {k: round(v, 4) for k, v in row.items()},
                   "graspNoise": list(noise)}
        try:
            scene = adapter.build_scene(sim_ir)
            # graspNoiseXYZ 已在 overrides：adapter.run 内部 build_scene_bundle 会把它
            # 放入 bundle["graspNoise"]，sequence 据此注入定位误差
            result = adapter.run(sim_ir, scene, float(sim_ir.get("timeout_s", 120.0)))
            run_rec["metrics"] = {k: v for k, v in result.metrics.items()
                                  if k in AGG_METRICS or k in ("pick_sequence_error",
                                                               "descend_failed",
                                                               "perception_failed")}
        except Exception as e:  # noqa: BLE001 — 单 run 失败不毁整批（failed 计数如实标注）
            run_rec["error"] = str(e)[:300]
            log.error("sim run failed, continuing batch", i=i, error=str(e))
        run_rec["wall_s"] = round(time.monotonic() - t0, 1)
        runs.append(run_rec)
        log.info("sim experiment run", i=i + 1, n=n, wall_s=run_rec["wall_s"],
                 pick_success=run_rec.get("metrics", {}).get("pick_success"),
                 depth_noise_mm=row.get("depth_noise_mm"))
        if progress_cb is not None:
            progress_cb(i + 1, n)
    batch_wall = time.monotonic() - t_batch

    return aggregate_runs(experiment, runs, names, X, batch_wall)


def aggregate_runs(experiment: dict, runs: list[dict], names: list[str],
                   X: np.ndarray, batch_wall_s: float) -> dict:
    ok_runs = [r for r in runs if r.get("metrics", {}).get("pick_sequence_error") is None
               and "error" not in r]
    failed = len(runs) - len(ok_runs)
    success = [float(r["metrics"].get("pick_success", 0.0)) for r in ok_runs]
    k = sum(1 for s in success if s >= 1.0)

    def _pct(key: str, q: float) -> float | None:
        vals = [float(r["metrics"][key]) for r in ok_runs if key in r.get("metrics", {})]
        return round(float(np.percentile(vals, q)), 3) if vals else None

    def _mean(key: str) -> float | None:
        vals = [float(r["metrics"][key]) for r in ok_runs if key in r.get("metrics", {})]
        return round(float(np.mean(vals)), 3) if vals else None

    aggregates = {
        "samples": len(runs),
        "completed": len(ok_runs),
        "failed": failed,
        "method": experiment["sampling"].get("method", "lhs"),
        "pick_success_rate": round(k / len(ok_runs), 4) if ok_runs else None,
        "pick_success_rate_ci95_wilson": _wilson(k, len(ok_runs)),
        "cycle_time_s_mean": _mean("cycle_time_s"),
        "cycle_time_s_P95": _pct("cycle_time_s", 95),
        "position_error_mm_mean": _mean("position_error_mm"),
        "position_error_mm_P95": _pct("position_error_mm", 95),
        "collision_count_mean": _mean("collision_count"),
        # V0.5 W3：感知定位误差（真实感知链实测，vs 零件真值）——DoD 指标
        "perception_error_mm_mean": _mean("perception_error_mm"),
        "perception_error_mm_P95": _pct("perception_error_mm", 95),
        # dev-plan W4 假设验证：单工作站 N 次 headless 耗时曲线
        "wall_total_s": round(batch_wall_s, 1),
        "wall_per_run_s_mean": round(batch_wall_s / len(runs), 1) if runs else None,
    }

    X_ok = np.array([X[r["i"]] for r in ok_runs]) if ok_runs else np.empty((0, len(names)))
    y_success = [float(r["metrics"].get("pick_success", 0.0)) for r in ok_runs]
    y_pos = [float(r["metrics"]["position_error_mm"]) for r in ok_runs
             if "position_error_mm" in r.get("metrics", {})]
    X_pos = np.array([X[r["i"]] for r in ok_runs
                      if "position_error_mm" in r.get("metrics", {})])
    sens_success, r2_s = _src(X_ok, names, np.asarray(y_success))
    sens_pos, r2_p = _src(X_pos, names, np.asarray(y_pos))

    assumptions = [
        {"name": "depth_noise_mapping", "provenance": "literature",
         "note": ("感知闭环（V0.5 W3）：depth_noise_mm → 深度帧噪声（帧偏置 N(0,σ) 主导"
                  "+逐像素 iid σ/10 次要）→ 反投影质心 → 控制目标；无感知模板时回退"
                  "N(0,σ) 三轴独立注入（各向同性近似）")},
        {"name": "unmapped_params", "provenance": "literature",
         "note": "illumination_lux/occlusion_percent/network_latency_ms 未映射到仿真"
                 "（脚本化抓取无感知链）——其敏感性≈0 是映射边界，非物理结论"},
        {"name": "sensitivity_method", "provenance": "literature",
         "note": f"SRC（Pearson r²）一阶排序，N={len(ok_runs)}；Saltelli-Sobol 需 "
                 "N×(2k+2) 次仿真求值（6 参数 base N=256 → 3584 次），单工作站不可行"},
    ]

    return {
        "experimentId": experiment.get("id", ""),
        "backend": "simulator",
        "aggregates": aggregates,
        "sensitivity": sens_success,
        "sensitivityPositionError": sens_pos,
        "assumptions": assumptions,
        "rSquared": {"pick_success": r2_s, "position_error_mm": r2_p},
        # 逐 run 明细（参数实例 + 指标 + 单次耗时）——留 job payload，可追溯可复算
        "runs": runs,
    }


_aggregate = aggregate_runs  # 旧名兼容（单测引用）


def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson 置信区间（小样本二值比例，比正态近似诚实）。"""
    if n == 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _src(X: np.ndarray, names: list[str], y: np.ndarray) -> tuple[list[dict], float | None]:
    """一阶 SRC：Pearson r²（=标准化回归系数平方，单因子）。

    y 无方差（全部成功/全部失败）时排名不可判，share 全 0 如实返回。
    R² 为多元线性模型的方差解释比（响应非线性时 <1，随结果标注不掩盖）。
    """
    if X.size == 0 or y.size == 0 or float(np.std(y)) < 1e-12:
        return ([{"name": n, "share": 0.0,
                  "note": "响应无方差，排名不可判（全部成功或全部失败）"} for n in names],
                None)
    shares = []
    for j, name in enumerate(names):
        xj = X[:, j]
        if float(np.std(xj)) < 1e-12:
            shares.append({"name": name, "share": 0.0})
            continue
        r = float(np.corrcoef(xj, y)[0, 1])
        shares.append({"name": name, "share": round(max(r * r, 0.0), 4)
                       if not np.isnan(r) else 0.0})
    shares.sort(key=lambda d: -d["share"])
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    r2 = float(1.0 - np.sum((y - A @ coef) ** 2) / np.sum((y - np.mean(y)) ** 2))
    return shares, round(max(0.0, min(r2, 1.0)), 4)
