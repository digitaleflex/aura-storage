"""Aucune fonction ni classe ne doit être définie deux fois dans un même module.

Python garde silencieusement la DERNIÈRE définition. C'est ce qui est arrivé le
2026-11-23 : une seconde `_public_page_headers()` ajoutée pour les pages de profil
a remplacé la première, et les pages de partage de dossier ont perdu leur
Content-Security-Policy sans aucune erreur (ruff F811 ne le signale pas quand la
première définition est utilisée entre les deux).

Le test lit le code source (AST) : il ne démarre aucune application.
"""
import ast
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("api", "audiobook")


def _duplicates(path: Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    seen: dict[str, list[int]] = collections.defaultdict(list)
    for node in tree.body:  # niveau module seulement : les méthodes de classe sont à part
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seen[node.name].append(node.lineno)
    return {name: lines for name, lines in seen.items() if len(lines) > 1}


def test_no_module_defines_the_same_function_or_class_twice():
    problems = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            for name, lines in _duplicates(path).items():
                problems.append(f"{path.relative_to(ROOT)}: {name}() lignes {lines}")
    assert not problems, "définitions en double (la dernière écrase la première) :\n" + "\n".join(problems)


def test_the_guard_detects_a_duplicate(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("def a():\n    return 1\n\n\ndef a():\n    return 2\n", encoding="utf-8")
    assert _duplicates(sample) == {"a": [1, 5]}
