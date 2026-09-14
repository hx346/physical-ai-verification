"""IR Schema 加载与校验：双运行时共用 schemas/ 下的唯一权威契约（ADR-0001/0004）。"""

from functools import cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .config import settings

IR_NAMES = (
    "requirement", "task", "system", "state", "environment",
    "experiment", "simulation", "evidence", "asset",
)


@cache
def load_validator(ir_name: str) -> Draft202012Validator:
    if ir_name not in IR_NAMES:
        raise KeyError(f"unknown IR: {ir_name}")
    path = settings.schema_dir / "ir" / f"{ir_name}.schema.json"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate(ir_name: str, instance: object) -> list[str]:
    """返回错误信息列表；空列表 = 校验通过。"""
    errors = sorted(load_validator(ir_name).iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def require_valid(ir_name: str, instance: object) -> None:
    errors = validate(ir_name, instance)
    if errors:
        raise ValidationError(f"{ir_name} IR 校验失败: " + "; ".join(errors[:5]))


def schema_dir_exists() -> bool:
    return (Path(settings.schema_dir) / "ir").is_dir()
