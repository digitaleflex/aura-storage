# Lot 2 — implémentation (droits, accès, historique, pilotage)

**Date :** 2026-11-20  
**Statut :** fondation Lot 2 implémentée dans `audiobook/` (schéma, domaine, services, API, tests). Paiement réel, facturation et offline restent hors périmètre (Lots 3/4).  
**Prérequis :** Lot 1 en place ; migrations `0003_lot2.sql` appliquées.

## 1. Périmètre livré

### Droits, territoires et contrats
- Migration `0003_lot2.sql` : `contracts`, `rights_windows.contract_id`, `listeners.territory_code`, index de pilotage des refus.
- Contrats (admin) : `POST/GET /api/v1/admin/contracts`.
- Fenêtres de droits liées à un contrat (`contract_id` sur création de droits).
- Territoire auditeur : `PATCH /api/v1/me` (`territory_code`) ; utilisé par défaut par le résolveur si `X-Territory` absent.
- Résolution d'accès : droits actifs évalués au moment de la décision ; refus explicite `TERRITORY_RESTRICTED` si des droits existent mais pas pour le territoire ; édition/asset/compte non valides refusés.

### Entitlements et accès (sans facturation réelle)
- Grants manuels existants conservés ; **révocation** : `POST /api/v1/admin/entitlements/{id}/revoke`.
- Entitlements expirés/révoqués/suspendus n'accordent pas d'accès (vérification de validité/statut). Un livre en bibliothèque sans entitlement reste inaccessible.
- Politique de sources : `free`, entitlements directs `edition/work/plan_catalog` selon modèle (`free`, `paid`, `subscription`).

### Résolveur d'accès complet (socle)
- Vérifie compte actif, statut publication, droits actifs (temps/territoire/canal), disponibilité asset/piste, entitlement selon modèle, et **autorisation appareil** quand `X-Device-Id` est fourni (`DEVICE_NOT_AUTHORIZED` si inconnu/révoqué/non propriétaire).
- Décisions enregistrées dans `access_decisions` (allow/deny, raison, sources, politique, territoire, expiration) et auditées.

### Écoute, historique et statistiques personnelles (base)
- Complétion/reprise/synchronisation multi-appareils : fondations Lot 1 conservées (événements append-only, bail par édition, takeover, progression versionnée).
- `GET /api/v1/history` : historique de progression par édition (position, complétion, dernière activité).
- `GET /api/v1/stats` : statistiques personnelles de base (démarrés, terminés, en cours, dernière écoute, événements appliqués).

### Pilotage
- `GET /api/v1/admin/access-refusals` : tableau de bord des refus (par raison, par action, derniers refus avec édition).

## 2. API ajoutée/modifiée (Lot 2)

- `PATCH /api/v1/me` : accepte `territory_code`.
- `GET /api/v1/history`, `GET /api/v1/stats` (auditeur authentifié).
- `GET /api/v1/access/{edition_id}` : headers optionnels `X-Territory`, `X-Device-Id`.
- `POST /api/v1/playback/sessions` : `X-Territory` optionnel (device via body, vérifié).
- `POST /api/v1/playback/editions/{edition_id}/tracks/{track_id}/url` : `X-Territory`, `X-Device-Id` optionnels.
- Admin : `POST/GET /api/v1/admin/contracts`, `POST /api/v1/admin/entitlements/{id}/revoke`, `GET /api/v1/admin/access-refusals`.
- Admin droits : `contract_id` supporté sur création de fenêtre de droits.

## 3. Critères Lot 2 couverts (socle)

- Livre en bibliothèque sans droit → refus `NO_ACTIVE_ENTITLEMENT` (décision auditée).
- Entitlement expiré/révoqué → accès coupé ; droits retirés/expirés/territoire non autorisé → non diffusé (`NO_ACTIVE_RIGHTS` / `TERRITORY_RESTRICTED`).
- Suspension d'édition (Lot 1) et indisponibilité d'actif continuent de bloquer la diffusion.
- Décisions d'accès traçables avec raison/sources/expiration (INV-16) ; progression/idempotence/versioning conservés (INV-06, INV-13..15) ; publication sans validation refusée (INV-11/20).
- Tableau de bord des refus d'accès disponible.

## 4. Tests

```bash
export AUDIOBOOK_TEST_DSN="postgresql://USER:PASSWORD@HOST:5432/DB"
PYTHONPATH=$PWD .venv/bin/python -m pytest tests/audiobook_service -q
```

Ajouts Lot 2 (`tests/audiobook_service/test_lot2.py`) : bibliothèque sans entitlement, révocation/expiration d'entitlement, restriction territoriale/retrait de droits, autorisation appareil, historique/stats, tableau de bord des refus, contrats, territoire profil.

Résultat observé : **31 passed** (domaine + API Lot 1 + compléments Lot 1 + Lot 2).

## 5. Limites et suite

- **Cache court/invalidation** : décisions toujours calculées et enregistrées (TTL exposé) ; cache de lecture/invalidation fine à ajouter si besoin de performance.
- **Contrats/territoires avancés** : cycle de vie contrat complet, héritage/contraintes fines et résolution pays plus riche à étendre.
- **Plans/abonnements réels** : périmètre plan-catalog modélisé, mais périodes/renouvellement/paiement au Lot 3.
- **Statistiques** : base personnelle (progression/événements appliqués) ; agrégats analytiques/versionnés au Lot 5.
- **Charge/concurrence** : tests fonctionnels de concurrence/progression présents ; campagne de charge dédiée à planifier avant montée en trafic.
- **Offline/DRM** (Lot 4), **paiement/fiscalité** (Lot 3), **recherche avancée/notifications** (Lot 5) non implémentés.
- **Recommandations (2026-11-24, issues #300/#301)** : le scoring est extrait en fonction pure
  (`score_candidates`) et réutilisé par l'étagère « Pour vous » du portail public via
  `api/portal_recommendations.py` (repli sur l'heuristique locale en cas d'erreur).
  Préférences et recommandations sont couvertes par `tests/audiobook_service/test_lot2.py`
  (nécessitent `AUDIOBOOK_TEST_DSN`) et par des tests hors base dans
  `tests/test_portal_recommendations.py`. Le service est exposé derrière Traefik sur
  `AUDIOBOOK_DOMAIN` (par défaut `audiobook.<APP_DOMAIN>`) via le profil `audiobook`.
