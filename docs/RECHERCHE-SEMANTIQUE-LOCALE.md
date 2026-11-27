# Recherche sémantique locale du portail public (issue #321)

- **Date :** 27 novembre 2026
- **Statut :** implémenté, validé hors ligne ; aucune donnée privée transmise à un tiers
- **Source de vérité :** `api/portal_search.py`, `api/main.py::_filter_collections`

## Décision

Le portail conserve un **enrichissement local** : aucun service d'embedding, de LLM
ou de recherche externe n'est appelé. La requête, les métadonnées publiées et les
signaux de lecture ne quittent jamais AURA ; aucun consentement à un tiers n'est
donc requis. Un moteur externe resterait une décision produit séparée (coût,
rétention, juridiction) et ne sera pas activé tacitement.

Les goûts appris ne sont pas injectés dans la recherche : seules les recommandations
(`api/portal_recommendations.py`) utilisent déjà les favoris, la progression et les
auteurs, localement. La recherche conversationnelle multi-tours n'est pas
implémentée : elle exigerait un état de session côté portail et une politique de
rétention dédiée. Les critères « goûts » et « conversation » de #321 sont donc
**documentés comme non retenus** pour ce lot, sans prétendre qu'ils sont livrés.

## Mécanisme

`portal_search.canonicalize()` replie les accents puis remplace, sur des tokens
entiers, les variantes connues par un terme canonique partagé :

| Terme canonique | Variantes reconnues |
|---|---|
| `thriller` | polar, policier, suspense, crime |
| `romance` | romantique, amour, sentimental |
| `biographie` | autobiographie, mémoires |
| `fantastique` | fantasy, magie, merveilleux |
| `science-fiction` | science fiction, scifi, futuriste |
| `histoire` | historique, chronique |
| `humour` | comique, comédie |
| `poesie` | poème, poèmes, vers |
| `jeunesse` | ado, enfant, enfants |
| `intelligence artificielle` | IA, machine learning, apprentissage automatique |

La requête et le texte indexé (titre, auteur, catégories, thèmes) passent par la
même fonction. Les mots non reconnus conservent la recherche par mots-clés
existante, avec la logique ET et les filtres explicites inchangés. Le libellé
saisi reste visible dans l'URL et dans la page ; seule la correspondance est
normalisée. Les intentions déjà prises en charge (durée, auteur, tri) restent
prioritaires et l'explication affiche aussi « synonyme local » quand une
variante a été comprise.

## Repli

- `AURA_SEARCH_ENRICHMENT=0` désactive la canonicalisation et restaure exactement
  l'ancien appariement (repli opérationnel immédiat, sans redéploiement de code).
- Aucune exception n'est introduite dans le chemin de recherche : en cas de
  requête vide ou de terme inconnu, le comportement précédent est conservé.
- Les tests `tests/test_public_portal_phase3.py` couvrent l'enrichissement, le
  repli et l'appariement des facettes.

## Mesure avant/après

Commande :

```sh
.venv/bin/python scripts/measure-portal-search.py --output docs/search-relevance-2026-11-27.json
```

Jeu doré : 12 requêtes représentatives, 15 notices synthétiques utilisant
uniquement des titres de domaine public et les étiquettes publiques réservées ;
`recall@5` et rang réciproque moyen. Rapport brut :
[`search-relevance-2026-11-27.json`](search-relevance-2026-11-27.json).

| Indicateur | Avant | Après |
|---|---:|---:|
| `recall@5` moyen | 0,722 | **1,000** |
| rang réciproque moyen | 0,833 | **0,917** |

Cas notables : « polar » passe de 1 à 3 résultats attendus sur 3, « romantique »
de 1 à 2 sur 2, « mémoires » de 1 à 2 sur 2. La requête « IA » ne renvoyait que
des faux positifs dus à l'appariement par sous-chaîne (`ia` dans `futuriste`,
`romantique`, etc.) ; elle renvoie désormais les deux notices d'intelligence
artificielle. Les requêtes sans synonyme (« Nuit », « comédie », « requête
inconnue ») gardent exactement le même résultat : le repli est vérifié.

Limite méthodologique : il s'agit d'une mesure **hors ligne sur jeu doré**, pas
d'un test en ligne avec clics réels. Le portail ne journalise pas les clics de
résultats (aucune donnée de pertinence utilisateur n'est collectée) ; toute
mesure de terrain nécessiterait une décision séparée sur la télémétrie.
