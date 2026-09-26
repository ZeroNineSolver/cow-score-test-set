"""Validate every test case against schema/vector.schema.json.

Usage: python3 replayers/python/validate.py [vectors dir]
"""

import json
import sys
from pathlib import Path

import jsonschema

root = Path(__file__).parents[2]
validator = jsonschema.Draft202012Validator(json.loads((root / "schema/vector.schema.json").read_text()))
paths = sorted(Path(sys.argv[1] if len(sys.argv) > 1 else root / "vectors").glob("*.json"))
bad = 0
for path in paths:
    errors = list(validator.iter_errors(json.loads(path.read_text())))
    for e in errors:
        print(f"{path.name}: {list(e.path)}: {e.message}")
    bad += bool(errors)
print(f"{len(paths)} vectors, {bad} with schema errors")
sys.exit(1 if bad or not paths else 0)
