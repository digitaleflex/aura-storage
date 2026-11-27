"""scripts/audit_backend.py (issue #335): it runs, it agrees with an independent count,
and it keeps the load-time import graph of api/ free of cycles."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_backend.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=120, cwd=ROOT)


def test_the_audit_figures_match_an_independent_count():
    out = _run("--json")
    assert out.returncode == 0, out.stderr
    figures = json.loads(out.stdout)
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    routes = re.findall(r"^@app\.(?:get|post|put|patch|delete|head|options)\(", src, re.M)
    models = re.findall(r"^class \w+\((?:[\w.]*)BaseModel\)", src, re.M)
    assert figures["routes"] == len(routes)
    assert figures["models"] == len(models)
    assert figures["lines"] == len(src.splitlines())
    assert sum(d["routes"] for d in figures["domains"].values()) == len(routes)
    assert figures["duplicates"] == []


def test_api_modules_have_no_import_cycle_at_load_time():
    figures = json.loads(_run("--json").stdout)
    assert figures["cycles"] == [], "import cycle between api modules: " + str(figures["cycles"])


def test_the_markdown_report_is_complete_and_names_the_commit():
    out = _run()
    assert out.returncode == 0, out.stderr
    for heading in ("## 1. Chiffres", "## 2. Routes par domaine", "## 3. États globaux", "## 4. Graphe d'imports",
                    "## 6. Couplage des tests", "## 7. Fonctions les plus longues", "## 8. Inventaire des routes",
                    "## 9. Modèles Pydantic"):
        assert heading in out.stdout, heading
    assert "Commit analysé" in out.stdout
    assert _run().stdout == out.stdout  # deterministic
