# Publication des couvertures — mode d'emploi

Ce runbook couvre la chaîne complète : candidats externes → sélection →
publication → jaquette AURA pour les livres sans artwork. Toutes les commandes
sont **sans risque par défaut** (dry-run ou lecture seule), sauf celles qui
portent `--apply` / la validation explicite dans l'interface.

## Fichier de revue canonique

Tous les outils (API, scripts shell, scripts Python) utilisent le même fichier :

```
${AURA_COVER_REVIEW_FILE:-${AURA_DATA_DIR:-/srv/aura-storage}/cover-review/cover-candidates.json}
```

Le verrou associé est `<fichier>.lock`. Ne jamais éditer ce fichier à la main :
les écritures sont atomiques et partagées entre l'API et les scripts.

## 1. Rafraîchir les candidats et pré-sélectionner

```bash
./scripts/refresh_cover_review.sh
```

Cette commande, **sans rien publier** :

1. interroge Google Books, Open Library puis iTunes (limite :
   `AURA_COVER_CANDIDATE_LIMIT`, défaut 20) ;
2. pré-sélectionne automatiquement les correspondances sûres (titre exact,
   auteur exact, un seul candidat, hôte autorisé) ;
3. rend une page HTML consultable (`AURA_COVER_REVIEW_HTML`, défaut
   `/srv/aura-storage/cover-review.html`).

Vérifier la page HTML, puis exporter le fichier de sélections depuis celle-ci.

## 2. Simuler, puis publier

```bash
# Simulation : aucune image n'est téléchargée, aucun état n'est modifié.
./scripts/apply_cover_candidates.sh /chemin/vers/selections.json --dry-run

# Publication effective des choix validés.
./scripts/apply_cover_candidates.sh /chemin/vers/selections.json
```

Même opération depuis l'interface d'administration : `/admin/covers` →
cocher « Simulation » d'abord, puis « Appliquer les couvertures validées ».
Le bouton ne publie que les livres au statut « Choix validé · à publier ».

Garanties : HTTPS uniquement, hôtes limités à Open Library / Apple / Google
Books, pas de redirection, écritures atomiques, reprise après incident.

## 3. Jaquette AURA pour les livres sans artwork

Le rafraîchissement quotidien (`scripts/refresh_public_library.sh`) traite les
livres publiés sans couverture : artwork intégré, image sœur, puis jaquette
AURA générée localement (titre + auteur, palette du portail).

Rattrapage unique des livres déjà sondés (ceux qui n'avaient aucun artwork) :

```bash
AURA_REPO_ROOT=/srv/api docker compose exec -T \
  -e AURA_REPO_ROOT=/srv/api \
  api python - --apply --reprobe --limit 200 \
  < scripts/generate_audiobook_covers.py
```

Une jaquette générée est stockée sous `<object_key>.jacket.jpg` et marquée comme
**remplaçable** : une vraie couverture sélectionnée plus tard prendra le pas
dessus (clé `<object_key>.cover.jpg`). Une vraie couverture n'est jamais
écrasée par une sélection. `--no-jacket` désactive la génération si besoin.

## 4. Vérification

- Interface `/admin/covers` : indicateurs « Sans couverture », « À publier »,
  pourcentage de couverture, tri automatique des livres sans couverture en tête.
- `GET /covers/{object_id}.jpg` : `302` vers l'image signée quand `cover_key`
  est renseigné, `404` sinon.
- Le fichier de revue conserve `status`, `cover_key`, `applied_at` et
  l'historique des candidats ; aucun état n'est perdu lors d'un refresh borné.

## 5. Politique éditoriale : couverture réelle ou jaquette AURA

Le portail public n'affiche la couverture d'origine **que** pour les livres
marqués `emblematic_cover = 1` (hero, meilleures ventes, partages `og:image`).
Tous les autres gardent la jaquette typographique AURA, même lorsqu'un
`cover_key` existe : les jaquettes générées localement (`.jacket.jpg`) ne sont
donc jamais affichées comme « vraie » couverture sur le site.

Pour curater un livre depuis l'interface : `/admin/covers` → case
« Couverture réelle (emblématique) ». Côté API :

```bash
curl -X PUT -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{"emblematic": true}' \
  https://$API/api/v1/admin/objects/$OID/emblematic-cover
```

Le marqueur ne supprime ni l'image ni `cover_key` : c'est une décision
d'affichage réversible. Le changement peut mettre jusqu'à une minute à
apparaître sur les pages publiques mises en cache.

## Dépannage

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| Les candidats n'apparaissent pas dans l'admin | Fichier de revue absent ou chemin différent | Vérifier `AURA_COVER_REVIEW_FILE` / relancer `refresh_cover_review.sh` |
| Un choix validé reste « à publier » | Application non lancée, ou lot limité | Relancer `apply_cover_candidates.sh` avec un `--selected-limit` plus grand |
| `skipped` à l'application | Le livre a déjà une vraie couverture | Normal : seules les jaquettes générées sont remplaçables |
| Aucune jaquette pour un ancien livre | `cover_probe_at` déjà posé | Relancer avec `--reprobe` (voir §3) |
