# Chiffres réconciliés du dépôt

> Généré le 2026-11-27T08:53:59Z par `scripts/regenerate-doc-metrics.py`. Source de vérité fonctionnelle : [`ETAT-DES-FONCTIONNALITES.md`](ETAT-DES-FONCTIONNALITES.md). Ce snapshot remplace les chiffres des documents historiques (`output/STRUCTURED_MAP.md`, `docs/API-ROUTES-AUDIT.md`, `docs/ISSUES-AUDIT-2026-11.md`).

| Indicateur | Valeur régénérée | Méthode |
|---|---:|---|
| Routes HTTP dans `api/main.py` | 156 | AST via `scripts/audit_backend.py --json` |
| Fonctions de test Python | 654 | AST de `tests/test_*.py` (la suite collecte les paramétrisations, donc davantage de cas) |
| Fichiers de test frontend | 14 | `web/src/**/*.test.ts(x)` |
| Cas de test frontend | 102 | occurrences de `it(`/`test(` dans ces fichiers |

## États relevés dans la source de vérité

| État | Lignes |
|---|---:|
| Implémenté | 53 |
| Non exécuté | 1 |
| Non vérifié | 1 |
| Ouvert | 3 |
| Partiel | 4 |

Les statuts ci-dessus décrivent des **lignes de tableau** et non des issues GitHub : le suivi d'exécution reste le tracker. Aucun de ces chiffres n'est saisi à la main dans les documents historiques.
