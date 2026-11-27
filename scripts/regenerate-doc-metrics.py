#!/usr/bin/env python3
"""Regenerate the reconciled documentation figures (#324), read-only on code.

    python3 scripts/regenerate-doc-metrics.py            # write docs/code-metrics.json + .md
    python3 scripts/regenerate-doc-metrics.py --stdout   # JSON only

Routes come from scripts/audit_backend.py (AST of api/main.py); test counts from
the AST of tests/test_*.py and a regex over web/src *.test.ts(x); feature states
from the status column of docs/ETAT-DES-FONCTIONNALITES.md, which stays the
source of truth. Nothing is imported or executed, so no env or DB is needed.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STATUS_WORDS = (
    "Implémenté", "Partiel", "Bloqué", "Ouvert", "Différé", "Reporté",
    "Non vérifié", "Non exécuté", "Fait",
)


def routes() -> int:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_backend.py"), "--json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["routes"]


def backend_tests() -> int:
    total = 0
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        total += sum(
            1 for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return total


def frontend_tests() -> tuple[int, int]:
    files = cases = 0
    pattern = re.compile(r"\b(?:it|test)\s*\(")
    for path in (ROOT / "web" / "src").rglob("*.test.ts*"):
        files += 1
        cases += len(pattern.findall(path.read_text(encoding="utf-8")))
    return files, cases


def feature_states() -> dict[str, int]:
    text = (DOCS / "ETAT-DES-FONCTIONNALITES.md").read_text(encoding="utf-8")
    states: Counter[str] = Counter()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("*").strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in {"Indicateur", "Fonction", "Gate", "État", "---"}:
            continue
        for word in STATUS_WORDS:
            if cells[1].startswith(word):
                states[word] += 1
                break
    return dict(sorted(states.items()))


def collect() -> dict:
    fe_files, fe_cases = frontend_tests()
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ETAT-DES-FONCTIONNALITES.md",
        "routes_http": routes(),
        "tests_backend_functions": backend_tests(),
        "tests_frontend_files": fe_files,
        "tests_frontend_cases": fe_cases,
        "feature_states_in_source_of_truth": feature_states(),
    }


def markdown(data: dict) -> str:
    states = data["feature_states_in_source_of_truth"]
    rows = "\n".join(f"| {name} | {count} |" for name, count in states.items())
    return f"""# Chiffres réconciliés du dépôt

> Généré le {data['generated_at']} par `scripts/regenerate-doc-metrics.py`. Source de vérité fonctionnelle : [`ETAT-DES-FONCTIONNALITES.md`](ETAT-DES-FONCTIONNALITES.md). Ce snapshot remplace les chiffres des documents historiques (`output/STRUCTURED_MAP.md`, `docs/API-ROUTES-AUDIT.md`, `docs/ISSUES-AUDIT-2026-11.md`).

| Indicateur | Valeur régénérée | Méthode |
|---|---:|---|
| Routes HTTP dans `api/main.py` | {data['routes_http']} | AST via `scripts/audit_backend.py --json` |
| Fonctions de test Python | {data['tests_backend_functions']} | AST de `tests/test_*.py` (la suite collecte les paramétrisations, donc davantage de cas) |
| Fichiers de test frontend | {data['tests_frontend_files']} | `web/src/**/*.test.ts(x)` |
| Cas de test frontend | {data['tests_frontend_cases']} | occurrences de `it(`/`test(` dans ces fichiers |

## États relevés dans la source de vérité

| État | Lignes |
|---|---:|
{rows}

Les statuts ci-dessus décrivent des **lignes de tableau** et non des issues GitHub : le suivi d'exécution reste le tracker. Aucun de ces chiffres n'est saisi à la main dans les documents historiques.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stdout", action="store_true", help="print JSON instead of writing files")
    args = ap.parse_args()
    data = collect()
    if args.stdout:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    (DOCS / "code-metrics.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (DOCS / "CODE-METRICS.md").write_text(markdown(data), encoding="utf-8")
    print(f"routes={data['routes_http']} backend_tests={data['tests_backend_functions']} "
          f"frontend_cases={data['tests_frontend_cases']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
