# Qualité du code — outils, règles et chiffres de départ

Mise en place le 2026-11-23 (phase 0 de `ROADMAP-2026-11.md`). **Aucun changement du
comportement de l'application** : on ajoute des contrôles, on ne réécrit rien.

## Principe : bloquer ce qui est propre, compter le reste

- **Bloquant** : une règle qui passe déjà sur tout le dépôt. Elle ne peut plus régresser.
- **Avertissement** : une règle qui trouve encore des cas. Elle est **comptée** dans le
  résumé du run CI et réduite petit à petit, jamais d'un coup.
- **Plafond (« cliquet »)** pour le web : le nombre d'avertissements ESLint ne peut pas
  augmenter (`--max-warnings` dans `web/package.json`). Quand on en corrige, on **baisse**
  le plafond dans la même PR.

## Les contrôles

| Contrôle | Où | Statut |
|---|---|---|
| `lint-python` : ruff, règles de `pyproject.toml` (syntaxe, noms non définis, défauts modifiables, comparaisons fautives…) | `.github/workflows/quality.yml` | **bloquant** |
| `lint-web` : ESLint (dont `react-hooks/rules-of-hooks`) | idem | **bloquant** sur les erreurs et sur toute hausse des avertissements |
| ruff, règles avancées (imports inutilisés, modernisation, simplifications) | idem | avertissement (compte par règle) |
| mypy sur `api/` | idem | avertissement |
| `audit` : `pip-audit` et `npm audit` | idem | informatif |
| `coverage` : couverture des tests API | idem | informatif, sans seuil |
| Dependabot : mises à jour groupées, une PR par semaine et par domaine | `.github/dependabot.yml` | PR ordinaires, rien n'est fusionné automatiquement |
| `.editorconfig` | racine | réglages de base des éditeurs |

`react-hooks/rules-of-hooks` aurait attrapé le plantage de la page Partages (un hook
appelé après un `return` anticipé) : sur l'ancienne version du fichier, il signale
l'erreur à la ligne 69.

## Les lancer en local

```bash
# Python (depuis la racine)
pip install ruff==0.17.6 mypy==2.4.1 -r api/requirements.txt
ruff check api audiobook scripts tests        # bloquant : doit afficher « All checks passed! »
mypy                                          # avertissement (config dans pyproject.toml)
```

```bash
# Web
cd web && npm ci && npm run lint
```

## Chiffres de départ (2026-11-23, `main` au commit 52193e4)

| Mesure | Valeur |
|---|---:|
| ruff bloquant (api, audiobook, scripts, tests) | 0 problème |
| ESLint, erreurs | 0 |
| ESLint, avertissements | 18 (plafond fixé à 18) |
| ruff avancé, avertissements | 1 084, dont 485 imports inutilisés (presque tous dans `audiobook/`) |
| mypy sur `api/` | 33 points, 5 fichiers |
| Fonctions Python annotées (`->`) | 565 sur 1 001 |

Les 485 imports inutilisés viennent surtout du découpage du paquet `audiobook` (chaque
module a reçu tous les imports du fichier d'origine). Les supprimer est un correctif
mécanique (`ruff check --select F401 --fix`) à faire dans une PR à part, validé par les
tests.

## Comment réduire la dette

1. Choisir **une règle** et la corriger partout (par exemple `F401` dans `audiobook/`).
2. Quand son compte tombe à zéro, la **déplacer** de l'avertissement vers le bloquant :
   l'ajouter à `select` dans `pyproject.toml` (et la retirer de la liste d'avertissement
   du workflow).
3. Côté web, baisser `--max-warnings` au nouveau compte.

## Ce qui n'est pas encore fait (à décider)

- Formateur automatique (ruff format, Prettier) : il réécrirait presque tous les fichiers.
  À faire seul, dans une PR sans autre changement, avec l'accord du propriétaire.
- Seuil de couverture : à fixer une fois la valeur de départ connue (voir le résumé du job
  `coverage`).
- mypy plus strict (`check_untyped_defs`, puis `disallow_untyped_defs`) : après la
  réduction des 33 points actuels.
