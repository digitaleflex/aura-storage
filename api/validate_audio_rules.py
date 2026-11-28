"""Validate api/audio_rules.json format.

Usage:
  python -m api.validate_audio_rules
  python -m api.validate_audio_rules path/to/audio_rules.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def validate_rules(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"file not found: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"invalid JSON: {e}"]
    rules = data.get("categories") if isinstance(data, dict) else data
    if not isinstance(rules, list):
        return ["root.categories must be a list (or root must be a list)"]
    seen = set()
    for i, item in enumerate(rules):
        if not isinstance(item, dict):
            errors.append(f"[{i}] must be an object")
            continue
        cat = item.get("category")
        kws = item.get("keywords")
        if not isinstance(cat, str) or not cat.strip():
            errors.append(f"[{i}] category must be a non-empty string")
            continue
        cat_n = cat.strip().lower()
        if cat_n in seen:
            errors.append(f"[{i}] duplicate category: {cat_n}")
        seen.add(cat_n)
        if not isinstance(kws, list) or not any(str(k).strip() for k in kws):
            errors.append(f"[{i}] {cat_n}: keywords must be a non-empty list")
            continue
        for j, kw in enumerate(kws):
            if not isinstance(kw, str) or not kw.strip():
                errors.append(f"[{i}] {cat_n}.keywords[{j}] must be non-empty string")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "audio_rules.json"
    errors = validate_rules(path)
    if errors:
        print(f"INVALID {path}")
        for e in errors:
            print(f"- {e}")
        return 1
    print(f"OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
