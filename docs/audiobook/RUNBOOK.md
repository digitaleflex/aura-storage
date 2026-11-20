# Audiobook — Runbook & administration (Lot 1)

Ce document couvre l'exploitation de base du service `audiobook/` (Lot 1). Le service est un bounded context séparé : il ne lit jamais les tables AURA et n'émet une URL média qu'après une décision d'accès `ALLOW`.

## 1. Configuration

Variables principales :

| Variable | Rôle | Note |
|---|---|---|
| `AUDIOBOOK_DSN` | DSN PostgreSQL | Obligatoire |
| `AUDIOBOOK_SCHEMA` | Schéma dédié | Défaut `audiobook` ; migrations versionnées |
| `AUDIOBOOK_PUBLIC_BASE_URL` | URL publique du service | Utilisée pour l'OIDC callback |
| `AUDIOBOOK_COOKIE_SECURE` | Cookies `Secure` | `1` en HTTPS, `0` uniquement en local HTTP |
| `AUDIOBOOK_DEV_AUTH` | Active `/api/v1/auth/dev-login` | **Doit être `0`/absent en production** |
| `AUDIOBOOK_ADMIN_TOKEN` | Bearer token admin bootstrap | Temporaire ; remplacer par SSO/rôles en prod |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OIDC auditeurs | Callback : `${AUDIOBOOK_PUBLIC_BASE_URL}/api/v1/auth/google/callback` |
| `AURA_API_BASE_URL` / `AURA_SERVICE_TOKEN` | Adapter `StoragePort` | Identité de service AURA à privilèges minimaux ; hors dev, requis |
| `AUDIOBOOK_MAX_DEVICES` | Limite appareils actifs | Défaut 3 (D-11) |
| `AUDIOBOOK_MAX_SIMULTANEOUS_SESSIONS` | Sessions de lecture simultanées | Défaut 2 (D-11) |
| `AUDIOBOOK_PLAYBACK_LEASE_SECONDS` | Bail de session active | Défaut 120 |
| `AUDIOBOOK_ACCESS_DECISION_TTL_SECONDS` | TTL décision/URL | Défaut 60 (court) |

Ne jamais exposer `AUDIOBOOK_ADMIN_TOKEN`, `AURA_SERVICE_TOKEN`, secrets OIDC ou DSN dans les logs/réponses.

## 2. Démarrage et santé

```bash
.venv/bin/python -m uvicorn audiobook.main:create_app --factory --host 0.0.0.0 --port 8080
```

- `GET /health/live` : processus vivant.
- `GET /health/ready` : base accessible (503 si indisponible).
- Au démarrage, `create_app` applique les migrations en attente dans le schéma configuré (`schema_migrations`).

## 3. Bootstrap admin — publier un livre gratuit (3 pistes)

Toutes les routes admin requièrent `Authorization: Bearer $AUDIOBOOK_ADMIN_TOKEN`.

1. Créer l'œuvre : `POST /api/v1/admin/works` (`title`, `language`, `description`).
2. Lier contributeurs : `POST /api/v1/admin/works/{work_id}/contributors` avec `role=author` et `role=narrator`.
3. Approuver l'œuvre : `POST /api/v1/admin/works/{work_id}/approve`.
4. Enregistrer les assets prêts (références AURA) : `POST /api/v1/admin/assets` (`storage_object_id`, `kind`, `content_type`, `duration_ms`, `status=ready`, couverture `kind=cover`).
5. Créer l'édition : `POST /api/v1/admin/editions` (`work_id`, `title`, `language`, `description`, `duration_ms`, `cover_asset_id`, `access_model=free`).
6. Créer les pistes (1..N) : `POST /api/v1/admin/editions/{edition_id}/tracks` (`position`, `title`, `start_ms`, `end_ms`, `asset_id`, `status=ready`).
7. Créer une fenêtre de droits active : `POST /api/v1/admin/editions/{edition_id}/rights` (`starts_at`, `ends_at`, `territory_code=WORLD`, `channel=stream`, `status=active`).
8. Publier : `POST /api/v1/admin/editions/{edition_id}/publish`. La publication échoue avec des blockers explicites si les prérequis ne sont pas satisfaits.

## 4. Opérations courantes

- **Suspendre/réactiver une édition** : `POST /api/v1/admin/editions/{id}/suspend` ou `/unsuspend`. Une édition suspendue n'est pas diffusable/publique.
- **Accorder/révoquer un droit** (manuel, sans paiement réel) : `POST /api/v1/admin/entitlements` ; révocation `POST /api/v1/admin/entitlements/{id}/revoke` (`reason`). Un entitlement expiré/révoqué coupe l'accès.
- **Contrats et droits** : `POST|GET /api/v1/admin/contracts` ; fenêtres de droits via `POST /api/v1/admin/editions/{edition_id}/rights` (`contract_id`, `territory_code`, dates/statut). Retirer/suspendre/expirer les droits coupe la diffusion.
- **Catégories / collections éditoriales** : `POST|GET /api/v1/admin/categories`, `POST|GET /api/v1/admin/editorial-collections`, ajout d'items, publication.
- **Audit et refus d'accès** : `GET /api/v1/admin/audit?limit=...` (append-only), tableau de bord `GET /api/v1/admin/access-refusals`.
- **Historique/stats auditeur** : `GET /api/v1/history`, `GET /api/v1/stats` (authentifié).
- **Vérifier le catalogue public** : `GET /api/v1/catalog`, `GET /api/v1/catalog/{edition_id}`.

## 5. Parcours de validation (tranche verticale)

1. Publier une édition gratuite avec 3 pistes.
2. Se connecter (dev-login en local, OIDC en environnement configuré).
3. Ajouter à la bibliothèque, obtenir une décision d'accès `ALLOW` avec sources `free` + droits.
4. Démarrer une session sur appareil A, envoyer des événements (`start/heartbeat/seek/pause/resume/ended`).
5. Démarrer sur appareil B sans `takeover` → conflit `ACTIVE_SESSION_EXISTS` ; avec `takeover` → nouvelle session active, l'ancienne ne peut plus avancer.
6. Vérifier `GET /api/v1/progress/{edition_id}` (progression autoritative, version, complétion monotone).
7. Vérifier `GET /api/v1/admin/audit` (accès, URL média, sessions, événements).

## 6. Sécurité et limites

- **Aucun contenu sans décision d'accès** : les URLs média sont émises par `StoragePort` uniquement après `ALLOW` enregistré ; le client ne fournit ni entitlement, ni prix, ni statut.
- **D-08** : le prototype AURA `/m/{slug}` ne doit pas exposer de contenu payant/soumis à droits. Avant toute ouverture, retirer/migrer cet accès et ne conserver que des previews explicitement publiques si décidé.
- **Secrets** : ne jamais utiliser `AUDIOBOOK_DEV_AUTH=1` ni un token admin statique partagé en production.
- **Limites** : appareils et sessions simultanées bornés (D-11), bail par édition, refus download (D-06/Lot 4).
- **D-10** : la demande de suppression révoque les accès/sessions et marque le compte `pending_deletion` ; l'anonymisation/purge conforme aux durées légales doit être exécutée et validée avant ouverture.

## 7. Sauvegarde et reprise (D-12)

- Sauvegarder le PostgreSQL du domaine audiobook (base/schéma dédié) de manière indépendante.
- Tester la restauration (RTO/RPO) avant toute ouverture payante.
- Après restauration, vérifier l'intégrité des références d'assets AURA et la cohérence des progressions/décisions critiques.

## 8. Incidents courants

| Symptôme | Piste |
|---|---|
| 503 `DATABASE_UNAVAILABLE` | DSN/schéma, connectivité PostgreSQL, migrations |
| 503 `STORAGE_UNAVAILABLE` / config | `AURA_API_BASE_URL`, `AURA_SERVICE_TOKEN`, santé AURA, privilèges preview-intent |
| 409 `ACTIVE_SESSION_EXISTS` | Conflit normal multi-appareils : reprendre depuis progression autoritative ou `takeover` explicite |
| 409 `TOO_MANY_ACTIVE_SESSIONS` / `TOO_MANY_DEVICES` | Limites D-11 atteintes : révoquer appareil/session inactif ou ajuster paramètre audité |
| 403 `EDITION_NOT_PUBLISHED` / `NO_ACTIVE_RIGHTS` / `ASSET_UNAVAILABLE` | Vérifier publication, fenêtre de droits, état des assets/pistes |
| Refus publication | Lire les blockers métier retournés (métadonnées, contributeurs, droits, assets, couverture) |
