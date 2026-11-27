# Audit structurel de l'API — constats et recommandations (issue #335)

> **Périmètre** : `api/` sur `main`, lecture seule. Aucun code applicatif n'a été modifié.
> **Reproductible** : `python3 scripts/audit_backend.py` régénère toutes les données
> ([`AUDIT-BACKEND-DONNEES.md`](AUDIT-BACKEND-DONNEES.md), avec le commit analysé en tête).
> Tout chiffre de ce document vient de ce script ; ce qui ne s'en déduit pas est marqué **risque** ou **recommandation**.

## 1. Constats prouvés

| # | Constat | Mesure |
|---|---|---|
| C1 | `api/main.py` concentre l'API | 6 619 lignes, 152 routes, 35 modèles Pydantic, 115 fonctions hors routes |
| C2 | Les routes ne sont pas la majorité du fichier | 3 727 lignes de routes, 1 474 de helpers, 328 de modèles : le reste est de l'initialisation et des constantes |
| C3 | Aucun cycle d'imports au chargement dans `api/` | 0 cycle ; `main` importe 19 modules, aucun module n'importe `main` |
| C4 | Le contrat OpenAPI est complet | 0 route `/api/v1` hors `openapi.yaml`, 0 route dupliquée |
| C5 | 11 structures mutables au niveau du module | 10 états (4 caches/compteurs : `_RESP_CACHE`, `_QUOTA`, `_LOGIN_ATTEMPTS`, `_PUBLIC_LOGIN_ATTEMPTS` ; 4 verrous ; `_READY_CACHE` ; `_THUMBNAIL_LOCKS`) + la table de limites `_PUBLIC_RATE_LIMITS` (configuration) ; aucune instruction `global` |
| C6 | Le cycle de vie est dans `main.py` | 5 `on_event("startup")`, 2 middlewares HTTP, 1 gestionnaire d'exceptions |
| C7 | Les tests ne dépendent que de 29 noms de `main` | `repo` (348 usages), `app` (205), `settings` (189), `reset_login_attempts` (79) ; les 25 autres noms : 1 à 8 usages |
| C8 | **28 routes n'ont aucun `Depends`** | toutes publiques par conception (liens `/s`, `/f`, `/m`, `/d`, `/a`, `/hls`, portail, santé, login) : elles se protègent par jeton, slug ou en ligne |
| C9 | Complexité très concentrée | 5 fonctions de plus de 80 lignes sur 267 ; `commit_object` (264 lignes, complexité 48), `_finalize_replacement_commit` (137 / 52), `upload_intent` (226 / 40) |
| C10 | Le portail est le plus gros domaine **et** le moins entremêlé | 38 routes, 28 helpers privés (274 lignes), seulement 5 helpers partagés et 1 état global |
| C11 | Les objets et les transferts sont le cœur partagé | 19 et 11 helpers partagés avec d'autres domaines ; les transferts touchent 2 états globaux |

## 2. Domaines : ce qui peut partir et à quel coût

Classés par couplage croissant (helpers partagés + états globaux), source : § 2 des données.

| Ordre | Domaine | Routes | Couplage | Remarque |
|---:|---|---:|---|---|
| 1 | collections | 6 | 2 partagés, 0 état | 72 lignes : trop petit pour être un pilote représentatif |
| 2 | import et révisions | 10 | 2 partagés, 0 état | workers déjà dans `import_worker.py` |
| 3 | dossiers | 8 | 2 partagés, 0 état | `update_folder` complexité 22 |
| 4 | **portail public** | 38 | 5 partagés, 1 état | déjà partiellement extrait (`public_ui`, `public_book`, `portal_search`, `portal_recommendations`, `magic_link`, `portal_assets/`) |
| 5 | médias publics | 7 | 7 partagés, 0 état | dépend du stockage S3 et du HLS |
| 6 | administration | 37 | 12 partagés, 0 état | nombreux modèles (12) ; surtout des routes `ADMIN_*` |
| 7 | partages | 7 | 8 partagés, 0 état | règles de portée et de révocation |
| 8 | objets | 24 | 19 partagés | carrefour : à découper en dernier |
| 9 | transferts | 7 | 11 partagés, 2 états, complexité 48 | **le plus risqué** : idempotence, intégrité, réconciliation |

## 3. Risques (non prouvés par le script, à garder en tête)

- **R1 — `main` bouge en parallèle.** Pendant cet audit, `main` a reçu des commits d'autres contributeurs (dont `0d840da`, qui a déplacé les limites de débit du portail vers un dépôt partagé : `repo.rate_hit`). Une extraction longue entre en conflit avec des PR en cours : **PR courtes, rebasées souvent, une à la fois sur `main.py`**.
- **R2 — Portée des états en mémoire.** Les caches, compteurs et verrous de C5 sont locaux au processus. Les déplacer dans un autre module ne change rien tant qu'ils restent des singletons de module ; en faire des attributs d'une classe instanciée par requête, ou les dupliquer par import mal ciblé, changerait leur portée. À traiter par un test de caractérisation avant déplacement.
- **R3 — Les 28 routes sans `Depends`.** Un déplacement qui perdrait un contrôle en ligne (jeton, slug, domaine) ne serait vu par aucune dépendance. Aucun test ne fige aujourd'hui la liste de ces routes.
- **R4 — Imports différés.** `main.py` en contient 17 (14 distincts : workers, `lifecycle`, `scrubber`, `portal_*`). Ce sont autant de choix de l'ordre de chargement qu'un déplacement peut casser ; ils n'indiquent pas de cycle (C3).
- **R5 — Noms privés lus par les tests** (`_PUBLIC_RATE_LIMITS`, `_QUOTA`, `_RESP_CACHE`, `_cache_key`, `_charge_quota`, `_usage_period`, `_portal_csp`) : il faudra des alias dans `main` ou des tests adaptés.

## 4. Recommandations

1. **Garder `main` comme façade de compatibilité** pendant toute la migration : `repo`, `app`, `settings`, `reset_login_attempts` doivent rester importables depuis `api.main` (C7 : 29 noms seulement, c'est peu).
2. **Utiliser des `APIRouter` par domaine** : c'est le gain principal ; les couches « application/domaine/infrastructure » du plan initial ne sont pas nécessaires pour sortir `main.py` de 6 000 lignes.
3. **Pilote : le portail public (#343)**, pas collections. Il est gros, peu couplé (C10), couvert par 68 tests, et ses modules d'appui existent déjà. Il dira ce que coûtent vraiment les états globaux et les routes sans `Depends`.
4. **Ordre ensuite** : schémas Pydantic (#340, aucune logique, ~330 lignes) → import/révisions → dossiers → médias publics → administration → partages → objets → transferts en dernier, par petites PR, en découpant d'abord `commit_object` et `upload_intent` (C9) *avant* de les déplacer.
5. **Avant le premier déplacement (#336)** : figer la liste des 152 routes avec leur méthode et leur règle d'accès, et en particulier **les 28 routes sans `Depends`** (R3). Le script le fournit déjà (§ 8 des données).
6. **Cibles chiffrées plutôt que « plus de logique métier »** : `main.py` < 5 000 lignes après les schémas et le portail ; < 3 000 après administration et dossiers.
7. **Un garde-fou qui existe déjà et qu'il faut garder** : `tests/test_no_duplicate_definitions.py` (une fonction définie deux fois a déjà fait perdre une CSP) et `tests/test_openapi_contract.py`. Ajouté avec cet audit : `tests/test_audit_backend.py` (le script tourne, ses chiffres concordent avec un décompte indépendant, sa sortie est déterministe ; aucun cycle d'imports). Une route nouvelle qui ne correspond à aucun motif de domaine apparaît sous « autre » dans le rapport, sans faire échouer la CI.

## 5. Ce que cet audit ne couvre pas
- Le **comportement** (pas de profilage ni de trace d'exécution) ; la complexité est une approximation McCabe par `ast`.
- Les appels dynamiques (`getattr`, enregistrement de routes à l'exécution) : le script ne voit que ce qui est écrit statiquement.
- Les graphes d'appel entre fonctions sont par nom de premier niveau ; deux fonctions de même nom dans des portées différentes seraient confondues.
- `db.py` / `db_pg.py` (2 329 et 2 032 lignes) : volontairement hors périmètre ici ; la duplication SQLite/PostgreSQL est un autre chantier.
