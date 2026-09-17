"""worker 处理器注册：导入即注册（runner 启动时加载本包）。"""

from . import calibration, experiment, simulation  # noqa: F401
