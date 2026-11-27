#!/usr/bin/env python3
"""Structural audit of the API (issue #335): reproducible, read-only, no import of the app.

    python3 scripts/audit_backend.py                 # Markdown on stdout
    python3 scripts/audit_backend.py -o report.md    # to a file
    python3 scripts/audit_backend.py --json          # raw figures

Everything is derived from the source with `ast` and `re`: nothing is executed, no
database or network is needed, and two runs on the same commit give the same output.
"""
import argparse
import ast
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
MAIN = API / "main.py"
HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}

# (domain, regex on the path). First match wins; order matters.
DOMAINS = [
    ("médias publics (/m /d /a /hls /covers)", r"^/(m/|d/|a/|hls/|covers/)"),
    ("portail public", r"^/(api/public/|livre/|extrait/|sitemap\.xml|robots\.txt|sw\.js|hors-ligne|portal-assets/|profil|connexion/|$)"),
    ("partages (objets et dossiers)", r"^/(s/|f/|p/|api/v1/(shares|folder-shares|objects/\{oid\}/shares?))"),
    ("administration", r"^/api/v1/(admin/|me/master-mode)"),
    ("authentification console", r"^/api/v1/(login|logout|me\b|session|auth)"),
    ("transferts", r"^/api/v1/(transfers|objects/(upload-intents|\{oid\}/(commit|abort|parts|multipart))|upload|multipart)"),
    ("collections", r"^/api/v1/collections"),
    ("dossiers", r"^/api/v1/folders"),
    ("import et révisions", r"^/api/v1/(import|objects/\{oid\}/revisions)"),
    ("objets (catalogue, médias, corbeille)", r"^/api/v1/(objects|trash|tags)"),
    ("santé et diagnostic", r"^/(health|ready|metrics|api/v1/(health|diag|netinfo))"),
]


def domain_of(path: str) -> str:
    for name, pattern in DOMAINS:
        if re.match(pattern, path):
            return name
    return "autre"


def span(node) -> int:
    return node.end_lineno - node.lineno + 1


def complexity(node) -> int:
    """McCabe-style: 1 + decision points."""
    n = 1
    for sub in ast.walk(node):
        if isinstance(sub, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler,
                            ast.With, ast.AsyncWith, ast.Assert)):
            n += 1
        elif isinstance(sub, ast.BoolOp):
            n += len(sub.values) - 1
        elif isinstance(sub, ast.comprehension):
            n += 1 + len(sub.ifs)
    return n


def route_of(func):
    """(method, path) of the first @app.<verb>("path") decorator, else None."""
    for dec in func.decorator_list:
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                and dec.func.attr in HTTP and dec.args and isinstance(dec.args[0], ast.Constant)):
            return dec.func.attr.upper(), dec.args[0].value
    return None


def guards_of(func) -> str:
    """Compact text of the Depends(...) defaults: the access rule of the route."""
    found = []
    args = func.args
    for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
        text = ast.unparse(default)
        if "Depends(" in text:
            found.append(re.sub(r"\s+", " ", text))
    return "; ".join(found)


def names_loaded(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def mutable_literal(value) -> bool:
    if isinstance(value, (ast.Dict, ast.List, ast.Set)):
        return True
    if isinstance(value, ast.Call):
        callee = ast.unparse(value.func)
        return callee in {"dict", "list", "set", "defaultdict", "collections.defaultdict", "OrderedDict",
                          "threading.Lock", "threading.RLock", "threading.Event", "Lock", "RLock",
                          "collections.deque", "deque", "TTLCache"}
    return False


def analyse_main():
    src = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = len(src.splitlines())
    routes, models, functions, classes = [], [], [], []
    globals_state, global_stmts, lazy_imports, threads = [], [], [], []
    handlers = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = {"name": node.name, "line": node.lineno, "lines": span(node), "cx": complexity(node),
                    "async": isinstance(node, ast.AsyncFunctionDef), "node": node}
            r = route_of(node)
            if r:
                info.update(method=r[0], path=r[1], guards=guards_of(node), domain=domain_of(r[1]))
                routes.append(info)
            else:
                for dec in node.decorator_list:
                    text = ast.unparse(dec)
                    if text.startswith("app.on_event") or text.startswith("app.exception_handler") \
                            or text.startswith("app.middleware"):
                        handlers.append({"name": node.name, "line": node.lineno, "decorator": text})
                functions.append(info)
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            entry = {"name": node.name, "line": node.lineno, "lines": span(node), "bases": bases}
            (models if any("BaseModel" in b for b in bases) else classes).append(entry)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and value is not None and mutable_literal(value):
                    globals_state.append({"name": t.id, "line": node.lineno, "kind": ast.unparse(value)[:60]})
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            global_stmts.extend(node.names)
        if isinstance(node, ast.Call):
            callee = ast.unparse(node.func)
            if callee in {"threading.Thread", "Thread", "asyncio.create_task", "threading.Timer"}:
                threads.append({"line": node.lineno, "call": callee})
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(fn):
                if isinstance(sub, (ast.Import, ast.ImportFrom)) and sub is not fn:
                    lazy_imports.append({"in": fn.name, "line": sub.lineno, "stmt": ast.unparse(sub)})
    return {"tree": tree, "lines": lines, "bytes": len(src.encode()), "routes": routes, "models": models,
            "classes": classes, "functions": functions, "state": globals_state, "global_stmts": sorted(set(global_stmts)),
            "lazy_imports": lazy_imports, "threads": threads, "handlers": handlers}


def module_imports(path: Path):
    """Intra-package edges of one api module: (target, lazy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    edges = set()
    top = {id(n) for n in tree.body}
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                targets.append(node.module.split(".")[0])
            else:
                targets.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("api."):
            targets.append(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            targets.extend(a.name.split(".")[1] for a in node.names if a.name.startswith("api."))
        for t in targets:
            if (API / f"{t}.py").exists():
                edges.add((t, id(node) not in top and not _is_top_nested(tree, node)))
    return edges


def _is_top_nested(tree, node) -> bool:
    return any(node is n for n in tree.body)


def import_graph():
    graph, lazy = {}, {}
    for path in sorted(API.glob("*.py")):
        if path.name == "__init__.py":
            continue
        name = path.stem
        graph[name] = set()
        lazy[name] = set()
        for target, is_lazy in module_imports(path):
            if target == name:
                continue
            (lazy if is_lazy else graph)[name].add(target)
    return graph, lazy


def find_cycles(graph):
    cycles, state, stack = [], {}, []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in sorted(graph.get(n, ())):
            if state.get(m) == 1:
                cycles.append(stack[stack.index(m):] + [m])
            elif state.get(m) is None:
                visit(m)
        stack.pop()
        state[n] = 2

    for n in sorted(graph):
        if state.get(n) is None:
            visit(n)
    return cycles


def module_table():
    rows = []
    for path in sorted(API.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        doc = ast.get_docstring(ast.parse(text)) or ""
        rows.append((path.name, len(text.splitlines()), doc.strip().splitlines()[0][:100] if doc.strip() else ""))
    return rows


def test_coupling():
    """How tests reach into api.main: attribute names used as `main.<name>`."""
    counts, files = collections.Counter(), collections.defaultdict(set)
    for path in sorted((ROOT / "tests").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"import api\.main as main|from api import main|from api\.main import", text):
            continue
        for name in re.findall(r"\bmain\.([A-Za-z_][A-Za-z0-9_]*)", text):
            counts[name] += 1
            files[name].add(path.name)
        for block in re.findall(r"from api\.main import \(?([^)\n]+)", text):
            for name in re.split(r"[,\s]+", block.strip()):
                if name and name != "as":
                    counts[name] += 1
                    files[name].add(path.name)
    return counts, files


def openapi_paths():
    path = ROOT / "docs" / "openapi.yaml"
    out, in_paths = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("paths:"):
            in_paths = True
        elif in_paths and re.match(r"^\S", line):
            break
        elif in_paths:
            m = re.match(r"^  (/\S*):\s*$", line)
            if m:
                out.add(m.group(1))
    return out


def domain_analysis(main):
    """Per domain: routes, route lines, private helpers (only called from that domain),
    shared helpers, mutable globals touched. This is what decides the extraction order."""
    top_funcs = {f["name"]: f for f in main["functions"]}
    route_by_name = {r["name"]: r for r in main["routes"]}
    models = {m["name"] for m in main["models"]}
    state = {s["name"] for s in main["state"]}
    callers = collections.defaultdict(set)
    for fn in list(main["routes"]) + list(main["functions"]):
        for name in names_loaded(fn["node"]):
            if name in top_funcs and name != fn["name"]:
                callers[name].add(fn["name"])
    dom_of_fn = {n: r["domain"] for n, r in route_by_name.items()}

    def domains_reaching(name, seen=None):
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)
        found = set()
        for c in callers.get(name, ()):
            if c in dom_of_fn:
                found.add(dom_of_fn[c])
            else:
                found |= domains_reaching(c, seen)
        return found

    rows = collections.defaultdict(lambda: {"routes": 0, "route_lines": 0, "models": set(), "private": [],
                                            "shared": set(), "state": set(), "cx_max": 0})
    for r in main["routes"]:
        d = rows[r["domain"]]
        d["routes"] += 1
        d["route_lines"] += r["lines"]
        d["cx_max"] = max(d["cx_max"], r["cx"])
        loaded = names_loaded(r["node"])
        d["models"] |= loaded & models
        d["state"] |= loaded & state
        d["shared"] |= {n for n in loaded if n in top_funcs and len(domains_reaching(n)) > 1}
    for name, fn in top_funcs.items():
        reach = domains_reaching(name)
        if len(reach) == 1:
            rows[next(iter(reach))]["private"].append(fn)
            loaded = names_loaded(fn["node"])
            rows[next(iter(reach))]["state"] |= loaded & state
    return rows


def build():
    main = analyse_main()
    graph, lazy = import_graph()
    cycles = find_cycles(graph)
    counts, files = test_coupling()
    dom = domain_analysis(main)
    documented = openapi_paths()
    v1 = [r for r in main["routes"] if r["path"].startswith("/api/v1")]
    undocumented = sorted({r["path"] for r in v1} - documented)
    dup = [k for k, v in collections.Counter((r["method"], r["path"]) for r in main["routes"]).items() if v > 1]
    return main, graph, lazy, cycles, counts, files, dom, documented, undocumented, dup


def commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "api"], cwd=ROOT, capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return (sha or "inconnu") + (" (api/ modifié localement)" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "inconnu"


def markdown() -> str:
    main, graph, lazy, cycles, counts, files, dom, documented, undocumented, dup = build()
    routes = main["routes"]
    out = []
    w = out.append
    w("# Audit structurel de l'API — données (généré)\n")
    w("> Généré par `python3 scripts/audit_backend.py`. Ne pas modifier à la main : relancer le script.")
    w(f"> Commit analysé : `{commit()}`.\n")
    w("## 1. Chiffres de `api/main.py`\n")
    fn_total = sum(f["lines"] for f in main["functions"])
    route_total = sum(r["lines"] for r in routes)
    model_total = sum(m["lines"] for m in main["models"])
    w("| Mesure | Valeur |\n|---|---:|")
    w(f"| Lignes | {main['lines']} |\n| Taille (octets) | {main['bytes']} |")
    w(f"| Routes HTTP | {len(routes)} |\n| Modèles Pydantic | {len(main['models'])} ({model_total} lignes) |")
    w(f"| Fonctions de premier niveau hors routes | {len(main['functions'])} ({fn_total} lignes) |")
    w(f"| Lignes des fonctions de route | {route_total} |")
    w(f"| Autres classes | {len(main['classes'])} |")
    w(f"| Gestionnaires (on_event, middleware, exception) | {len(main['handlers'])} |")
    w(f"| Routes (méthode, chemin) dupliquées | {len(dup)} |")
    w(f"| Routes `/api/v1` absentes d'`openapi.yaml` | {len(undocumented)} |")
    w(f"| Routes hors `/api/v1` (hors contrat OpenAPI) | {len([r for r in routes if not r['path'].startswith('/api/v1')])} |")
    w("")
    w("## 2. Routes par domaine (classement par chemin)\n")
    w("| Domaine | Routes | Lignes de routes | Modèles utilisés | Helpers privés (lignes) | Helpers partagés | États globaux touchés | Complexité max |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, d in sorted(dom.items(), key=lambda kv: -kv[1]["routes"]):
        priv_lines = sum(f["lines"] for f in d["private"])
        w(f"| {name} | {d['routes']} | {d['route_lines']} | {len(d['models'])} | {len(d['private'])} ({priv_lines}) "
          f"| {len(d['shared'])} | {len(d['state'])} | {d['cx_max']} |")
    w("")
    w("*Helpers privés* : fonctions de `main.py` appelées (directement ou non) par les routes d'un seul domaine : "
      "elles peuvent partir avec lui. *Helpers partagés* : appelées depuis plusieurs domaines : elles doivent "
      "d'abord trouver un propriétaire commun.\n")
    w("## 3. États globaux et effets de bord\n")
    w("### Variables mutables de module\n")
    w("| Variable | Ligne | Construction |\n|---|---:|---|")
    for s in main["state"]:
        w(f"| `{s['name']}` | {s['line']} | `{s['kind']}` |")
    w(f"\nInstructions `global` : {', '.join('`'+n+'`' for n in main['global_stmts']) or 'aucune'}.\n")
    w("### Threads, tâches et gestionnaires\n")
    for t in main["threads"]:
        w(f"- `{t['call']}` ligne {t['line']}")
    for h in main["handlers"]:
        w(f"- `@{h['decorator']}` → `{h['name']}` (ligne {h['line']})")
    if not main["threads"] and not main["handlers"]:
        w("- aucun")
    w("")
    w("### Imports différés dans `main.py` (souvent des casse-cycles)\n")
    seen = collections.Counter(i["stmt"] for i in main["lazy_imports"])
    for stmt, n in seen.most_common(15):
        w(f"- `{stmt}` ×{n}")
    w("")
    w("## 4. Graphe d'imports entre modules de `api/`\n")
    w("| Module | Lignes | Importe (au chargement) | Importe (différé) | Importé par |\n|---|---:|---|---|---|")
    importers = collections.defaultdict(set)
    for m, targets in graph.items():
        for t in targets:
            importers[t].add(m)
    sizes = {r[0][:-3]: r[1] for r in module_table()}
    for m in sorted(graph):
        w(f"| `{m}` | {sizes.get(m, 0)} | {', '.join(sorted(graph[m])) or '—'} | {', '.join(sorted(lazy[m])) or '—'} "
          f"| {', '.join(sorted(importers[m])) or '—'} |")
    w("")
    w(f"Cycles d'imports au chargement : **{len(cycles)}**." + ("" if not cycles else " " + " ; ".join(" → ".join(c) for c in cycles)))
    w("")
    w("## 5. Modules existants réutilisables\n")
    w("| Fichier | Lignes | Rôle (docstring) |\n|---|---:|---|")
    for name, n, doc in module_table():
        w(f"| `{name}` | {n} | {doc or '—'} |")
    w("")
    w("## 6. Couplage des tests avec `api.main`\n")
    w("Noms lus ou modifiés par les tests sous la forme `main.<nom>` ou `from api.main import <nom>`. "
      "Déplacer un nom hors de `main` casse ces tests tant qu'ils ne sont pas adaptés ou qu'un alias est conservé.\n")
    private = [(n, c) for n, c in counts.most_common() if n.startswith("_")]
    public = [(n, c) for n, c in counts.most_common() if not n.startswith("_")]
    w(f"- Noms distincts : **{len(counts)}** (privés `_x` : {len(private)}, publics : {len(public)}), "
      f"dans **{len({f for fs in files.values() for f in fs})}** fichiers de test.")
    w("\n| Nom | Utilisations | Fichiers |\n|---|---:|---:|")
    for n, c in counts.most_common(25):
        w(f"| `{n}` | {c} | {len(files[n])} |")
    w("")
    w("## 7. Fonctions les plus longues et les plus complexes\n")
    allf = routes + main["functions"]
    w("| Fonction | Ligne | Lignes | Complexité | Type |\n|---|---:|---:|---:|---|")
    for f in sorted(allf, key=lambda f: -f["lines"])[:15]:
        w(f"| `{f['name']}` | {f['line']} | {f['lines']} | {f['cx']} | {'route ' + f['method'] + ' ' + f['path'] if 'path' in f else 'helper'} |")
    w("")
    w("| Fonction | Ligne | Complexité | Lignes |\n|---|---:|---:|---:|")
    for f in sorted(allf, key=lambda f: -f["cx"])[:15]:
        w(f"| `{f['name']}` | {f['line']} | {f['cx']} | {f['lines']} |")
    w(f"\nFonctions de plus de 80 lignes : **{sum(1 for f in allf if f['lines'] > 80)}** sur {len(allf)}.\n")
    w("## 8. Inventaire des routes\n")
    w("| Méthode | Chemin | Fonction | Ligne | Lignes | Domaine | Règle d'accès (Depends) |\n|---|---|---|---:|---:|---|---|")
    for r in routes:
        guard = r["guards"] or "**aucune dépendance déclarée**"
        w(f"| {r['method']} | `{r['path']}` | `{r['name']}` | {r['line']} | {r['lines']} | {r['domain']} | `{guard[:90]}` |")
    w("")
    w("## 9. Modèles Pydantic\n")
    w("| Modèle | Ligne | Lignes |\n|---|---:|---:|")
    for m in main["models"]:
        w(f"| `{m['name']}` | {m['line']} | {m['lines']} |")
    w("")
    if undocumented:
        w("## 10. Routes `/api/v1` non documentées dans `openapi.yaml`\n")
        for p in undocumented:
            w(f"- `{p}`")
        w("")
    return "\n".join(out) + "\n"


def as_json():
    main, graph, lazy, cycles, counts, files, dom, documented, undocumented, dup = build()
    return json.dumps({
        "lines": main["lines"], "routes": len(main["routes"]), "models": len(main["models"]),
        "functions": len(main["functions"]), "state": [s["name"] for s in main["state"]],
        "cycles": cycles, "undocumented": undocumented, "duplicates": [list(d) for d in dup],
        "domains": {k: {"routes": v["routes"], "route_lines": v["route_lines"]} for k, v in dom.items()},
        "test_names": len(counts),
    }, indent=2, ensure_ascii=False)


def main_cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--output", help="write to this file instead of stdout")
    ap.add_argument("--json", action="store_true", help="print raw figures as JSON")
    args = ap.parse_args(argv)
    text = as_json() + "\n" if args.json else markdown()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
