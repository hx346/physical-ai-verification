"""schema_loader 测试：examples 全部对 schema 通过（与 schemas/tools/validate.py 同源断言）。"""

from pathlib import Path

import yaml

from roboverify_runtime.schema_loader import validate

_EXAMPLES = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def test_all_examples_validate() -> None:
    checked = 0
    for ir_dir in sorted(_EXAMPLES.iterdir()):
        if not ir_dir.is_dir():
            continue
        for example_file in sorted(ir_dir.glob("*.yaml")):
            instances = yaml.safe_load(example_file.read_text(encoding="utf-8"))
            for instance in (instances if isinstance(instances, list) else [instances]):
                assert validate(ir_dir.name, instance) == [], f"{ir_dir.name}/{example_file.name}"
                checked += 1
    assert checked >= 20  # 21 个示例实例，防止 examples 目录被误删
