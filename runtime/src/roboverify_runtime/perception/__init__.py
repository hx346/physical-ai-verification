"""感知定位（V0.5 W3）：深度图 → 零件位姿假设。"""

from .depth_localize import apply_depth_noise, default_workspace, intrinsics_from_fov, localize_from_depth

__all__ = ["apply_depth_noise", "default_workspace", "intrinsics_from_fov",
           "localize_from_depth"]
