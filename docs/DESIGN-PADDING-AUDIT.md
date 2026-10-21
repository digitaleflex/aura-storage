# Audit des paddings arbitraires (P6 #171)

Valeurs hors échelle (`--space-*`) détectées dans `web/src/styles.css` :

| Valeur | Occurrences | Recommandation |
|---|---|---|
| 10px | 12 | `--space-3` (12px) ou `--space-2` (8px) |
| 11px | 3 | `--space-3` |
| 12px | 3 | `--space-3` (déjà dans l'échelle) |
| 13px | 1 | `--space-3` |
| 14px | 2 | `--space-3`/`--space-4` |
| 15px | 1 | `--space-4` |
| 16px | 4 | `--space-4` (déjà dans l'échelle) |
| 18px | 2 | `--space-4`/`--space-5` |

Action : remplacer progressivement ces valeurs par les tokens `--space-*` dans une PR dédiée. Non bloquant.
EOF
echo done