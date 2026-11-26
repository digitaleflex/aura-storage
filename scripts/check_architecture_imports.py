#!/usr/bin/env python3
"""Lightweight architecture import guard (#350)."""
from __future__ import annotations
import ast, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bad = []
for p in (ROOT / "api").rglob("*.py"):
    if p.name == "main.py":
        continue
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "api.main":
            # lazy imports inside functions are allowed; top-level is flagged
            if any(isinstance(parent, ast.Module) for parent in [None]):
                pass
    # simple: flag top-level from api.main import
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module in ("api.main", ".main"):
            bad.append(f"{p.relative_to(ROOT)}:{n.lineno} top-level import from main")
if bad:
    print("Architecture import warnings:")
    for b in bad:
        print(b)
    sys.exit(1)
print("ok")
