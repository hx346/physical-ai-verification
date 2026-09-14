#!/usr/bin/env python3
"""Validate all example YAML files under examples/ against schemas/ir/*.schema.json.

Convention: examples/<ir-name>/*.yaml is validated against ir/<ir-name>.schema.json.
Files whose top-level node is a list are validated item by item.

Usage: python schemas/tools/validate.py   (exit code 1 on any failure)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "ir"
EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples"


def main() -> int:
    failures = 0
    checked = 0
    for schema_path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        ir_name = schema_path.name.removesuffix(".schema.json")
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        example_dir = EXAMPLE_DIR / ir_name
        if not example_dir.is_dir():
            continue
        for example_path in sorted(example_dir.glob("*.yaml")):
            instances = yaml.safe_load(example_path.read_text(encoding="utf-8"))
            if instances is None:
                continue
            if not isinstance(instances, list):
                instances = [instances]
            for idx, instance in enumerate(instances):
                checked += 1
                errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
                for err in errors:
                    failures += 1
                    where = f"{example_path.name}[{idx}]" if len(instances) > 1 else example_path.name
                    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
                    print(f"FAIL {ir_name}/{where} at {path}: {err.message}")
    print(f"validated {checked} instance(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
