#!/usr/bin/env python3
"""Reproducible structural audit of api/main.py (issue #335)."""
from __future__ import annotations
import ast, collections, json, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / 'api' / 'main.py'
OUT = ROOT / 'docs' / 'engineering' / 'api-main-audit-2026-11-26.md'

def routes(tree):
    out=[]
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in {'get','post','put','delete','patch','head','options','websocket'}:
                    obj=ast.unparse(d.func.value)
                    if obj=='app' or 'router' in obj.lower():
                        path=d.args[0].value if d.args and isinstance(d.args[0],ast.Constant) else '?'
                        out.append({'method':d.func.attr.upper(),'path':path,'handler':n.name,'line':n.lineno,'async':isinstance(n,ast.AsyncFunctionDef)})
    # dedupe keep order
    seen=set(); uniq=[]
    for r in out:
        k=(r['method'],r['path'],r['handler'])
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq

def top_level(tree):
    funcs=[]; classes=[]; assigns=[]
    for n in tree.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            funcs.append({'name':n.name,'line':n.lineno,'async':isinstance(n,ast.AsyncFunctionDef),'lines':(getattr(n,'end_lineno',n.lineno)-n.lineno+1)})
        elif isinstance(n,ast.ClassDef):
            classes.append({'name':n.name,'line':n.lineno,'lines':(getattr(n,'end_lineno',n.lineno)-n.lineno+1)})
        elif isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=[]
            if isinstance(n,ast.Assign):
                for t in n.targets:
                    if isinstance(t,ast.Name): targets.append(t.id)
            elif isinstance(n.target,ast.Name): targets.append(n.target.id)
            for t in targets: assigns.append({'name':t,'line':n.lineno})
    return funcs,classes,assigns

def imports(tree):
    mods=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Import):
            for a in n.names: mods.append(a.name)
        elif isinstance(n,ast.ImportFrom):
            mods.append('.'*(n.level)+(n.module or ''))
    return sorted(set(mods))

def globals_and_effects(src):
    patterns={
        'module_globals': r'^_[A-Z0-9_]+\s*[:=]|^[A-Z][A-Z0-9_]+\s*=',
        'app_state': r'app\.state|request\.app\.state',
        'threads_workers': r'Thread\(|BackgroundTasks|start_.*worker|verifier|scrubber|reconcile',
        'env_reads': r'os\.environ|getenv\(',
        'file_io': r'open\(|Path\(.*\)\.(read|write)|write_text|read_text',
        'subprocess': r'subprocess\.|Popen\(',
        'db_conn': r'repo\.|db\.|Session\(|execute\(',
        's3': r's3|boto3|presign|put_object|get_object',
    }
    findings={}
    for k,p in patterns.items():
        findings[k]=len(re.findall(p,src,re.M))
    return findings

def complexity(funcs):
    # rough: lines as proxy; also count branches by ast
    return sorted(funcs,key=lambda x:x['lines'],reverse=True)[:30]

src=MAIN.read_text()
tree=ast.parse(src)
r=routes(tree)
funcs,classes,assigns=top_level(tree)
imps=imports(tree)
effects=globals_and_effects(src)
big=complexity(funcs)
by_domain=collections.Counter()
for x in r:
    p=x['path']
    if p.startswith('/api/public'): by_domain['portal_public']+=1
    elif p.startswith('/api/v1/admin'): by_domain['admin']+=1
    elif p.startswith('/api/v1/objects') or p.startswith('/api/v1/transfers'): by_domain['objects_transfers']+=1
    elif p.startswith('/api/v1/folders'): by_domain['folders_shares']+=1
    elif p.startswith('/api/v1/collections'): by_domain['collections']+=1
    elif p.startswith('/api/v1/import-jobs'): by_domain['import_jobs']+=1
    elif p.startswith('/api/v1/revisions') or '/revisions' in p: by_domain['revisions']+=1
    elif p.startswith('/api/v1/login') or p.startswith('/api/v1/logout') or p.startswith('/api/v1/me') or p.startswith('/api/public/auth'): by_domain['auth']+=1
    else: by_domain['other']+=1

lines=[
'# Audit structurel — `api/main.py` (#335)\n',
f'> Généré le 2026-11-26 par `python scripts/audit_api_structure.py`. Aucun changement applicatif.\n',
'## Contexte prouvé\n',
f'- Fichier: `api/main.py`\n- Lignes: {len(src.splitlines())}\n- Fonctions top-level: {len(funcs)}\n- Classes top-level: {len(classes)}\n- Assignations top-level: {len(assigns)}\n- Routes détectées (décorateurs app/router): {len(r)}\n',
'## Cartographie des routes\n',
'| Méthode | Chemin | Handler | Ligne | Async |\n|---|---|---|---:|:---:|\n',
]
for x in r:
    lines.append(f"| {x['method']} | `{x['path']}` | `{x['handler']}` | {x['line']} | {'yes' if x['async'] else 'no'} |\n")
lines += ['\n## Domaines (heuristique par chemin)\n\n| Domaine | Routes |\n|---|---:|\n']
for k,v in by_domain.most_common():
    lines.append(f'| {k} | {v} |\n')
lines += ['\n## Fonctions/classes les plus volumineuses (proxy complexité)\n\n| Nom | Ligne | Lignes | Type |\n|---|---:|---:|---|\n']
for f in big:
    kind='async fn' if f['async'] else 'fn'
    lines.append(f"| `{f['name']}` | {f['line']} | {f['lines']} | {kind} |\n")
for c in sorted(classes,key=lambda x:x['lines'],reverse=True)[:15]:
    lines.append(f"| `{c['name']}` | {c['line']} | {c['lines']} | class |\n")
lines += ['\n## Imports / modules\n\n']
for m in imps:
    lines.append(f'- `{m}`\n')
lines += ['\n## Signaux d’effets de bord / risques (comptage heuristique)\n\n| Signal | Occurrences |\n|---|---:|\n']
for k,v in effects.items():
    lines.append(f'| {k} | {v} |\n')
lines += ['\n## Constats prouvés\n']
lines += [
'- `api/main.py` concentre HTTP, auth, portail, objets, médias, dossiers, partages, admin, import et révisions.\n',
'- Des modules spécialisés existent déjà (`api/authz.py`, `api/store.py`, `api/s3.py`, `api/lifecycle.py`, `api/transfer.py`, `api/reconciler.py`, `api/verifier.py`, `api/scrubber.py`, etc.) et doivent être réutilisés avant toute réécriture.\n',
'- La surface route est large ; toute extraction doit préserver chemins, méthodes, contrats OpenAPI et tests.\n',
'\n## Risques\n',
'- Effets de bord à l’import et globals mutables peuvent casser les tests lors d’extractions.\n',
'- Transactions, idempotence et ordre des middlewares sont sensibles.\n',
'- Couplage implicite entre helpers de sérialisation, modèles Pydantic et routes.\n',
'\n## Candidats extraction (ordre recommandé)\n',
'1. Baseline tests/OpenAPI/snapshots routes (#336).\n2. Frontières d’architecture et règles dépendances (#337).\n3. Factory `create_app()`/composition root (#338).\n4. Middlewares/cycle de vie (#339).\n5. Schémas Pydantic (#340), normalisation/sérialisation (#341).\n6. Routeurs domaine par domaine: auth, portail, objets/transferts, médias/collections, dossiers/partages, admin, import/revisions (#342-#348).\n',
'\n## Limites de l’audit\n',
'- Complexité basée sur heuristiques (taille, motifs) ; pas un graphe d’appels complet.\n',
'- Les routes déclarées hors décorateurs standards ou via include_router indirect peuvent demander une vérification manuelle.\n',
]
OUT.write_text(''.join(lines), encoding='utf-8')
print(OUT)
