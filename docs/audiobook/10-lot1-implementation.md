# Lot 1 — implémentation (tranche verticale + compléments)

**Date :** 2026-11-20  
**Statut :** Lot 1 fonctionnellement implémenté dans le bounded context `audiobook/` (code + schéma + tests) ; **non déployé/intégré** à la stack Compose de production et non ouvert commercialement.  
**Décisions :** recommandations D-01 à D-12 **acceptées** ; ce document décrit l'implémentation réalisée et les conditions restantes avant exposition.

## 1. Périmètre livré

Tranche verticale initiale satisfaite : **publier un livre gratuit → écouter sur deux appareils → résoudre un conflit de progression → auditer les décisions d'accès**.

### Identité, comptes, sessions, appareils (DOM-01, D-03, D-11)
- Identité auditeur séparée d'AURA : `listeners`, `listener_identities` (OIDC provider/subject), sessions auth opaques hashées SHA-256 + CSRF, `devices`.
- Auth : `POST /api/v1/auth/dev-login` (**uniquement** `AUDIOBOOK_DEV_AUTH=1`), Google OIDC PKCE/state (`/api/v1/auth/google`, callback), `GET /api/v1/me`, `POST /api/v1/auth/logout`.
- Profil/préférences : `PATCH /api/v1/me` (nom, locale, fuseau), demande de suppression `POST /api/v1/me/deletion-request` (passage `pending_deletion`, révocation sessions auth/playback actives, audit/outbox ; workflow légal/anonymisation complet à finaliser selon D-10).
- Sessions auth : `GET/DELETE /api/v1/me/sessions/{id}`.
- Appareils : `GET/POST /api/v1/devices`, `POST /api/v1/devices/{id}/revoke` (révocation + abandon des sessions de lecture actives liées).
- **Limites D-11 appliquées** : `AUDIOBOOK_MAX_DEVICES` (défaut 3), `AUDIOBOOK_MAX_SIMULTANEOUS_SESSIONS` (défaut 2) refusées avec erreurs explicites (`TOO_MANY_DEVICES`, `TOO_MANY_ACTIVE_SESSIONS`) ; **1 bail de progression actif par (auditeur, édition)** avec `takeover` explicite.

### Catalogue, actifs, publication (DOM-02, DOM-04)
- Œuvres, contributeurs/rôles, éditions, pistes, chapitres, assets, fenêtres de droits (`rights_windows`).
- Publication bloquante via validation métier pure (`audiobook/domain.py::validate_publication`) : œuvre approuvée, auteur+narrateur, métadonnées, durée, couverture, pistes/assets prêts, fenêtre de droits non expirée.
- Suspension/réactivation d'édition : `POST /api/v1/admin/editions/{id}/suspend|unsuspend` (édition suspendue = inaccessible au streaming/publication catalogue).
- Catégories et collections éditoriales : tables + API admin/public (`/api/v1/categories`, `/api/v1/editorial-collections` publiées, création/ajout/publication admin).
- Critère Lot 1 validé : publication d'une édition gratuite avec **3 pistes** et écoute.

### Bibliothèque (DOM-03)
- Entrées, favoris, collections personnelles privées : ajout/retrait idempotent, suppression de collection sans suppression d'œuvre/entrée (`/api/v1/library`, `/api/v1/favorites`, `/api/v1/personal-collections`).
- Séparation stricte : présence en bibliothèque ≠ droit d'accès/entitlement.

### Accès, lecture, progression (DOM-05, DOM-06)
- Décision d'accès pure et explicable (`decide_access`) : compte actif, édition publiée, fenêtre de droits active, asset prêt, modèle `free` ou entitlement actif (`paid`/`subscription`), territoire. Téléchargement refusé en Lot 1 (`DOWNLOAD_NOT_ALLOWED`/non activé, D-06).
- Chaque décision enregistrée dans `access_decisions` et auditée ; URL média délivrée **uniquement** après `ALLOW` via `StoragePort` (AURA `preview-intent` en prod, fake en dev).
- Progression event-sourcée : `playback_sessions`, `listening_events` append-only (`event_id` unique, `client_seq` monotone), `listening_progress` canonique avec version/CAS, conflits/stales explicites, reprise, seek explicite, complétion monotone, idempotence.
- Endpoints : `GET /api/v1/access/{edition_id}`, `GET /api/v1/progress/{edition_id}`, `POST /api/v1/playback/sessions`, `POST /api/v1/playback/sessions/{id}/events`, `POST /api/v1/playback/editions/{edition_id}/tracks/{track_id}/url`.

### Administration, audit, observabilité (DOM-11)
- Admin bootstrap Bearer `AUDIOBOOK_ADMIN_TOKEN` (à remplacer par SSO/contrôle d'accès de production) : œuvres/contributeurs/approbation, éditions/assets/pistes/chapitres/droits, publication/suspension, entitlements manuels, catégories/collections éditoriales, audit (`GET /api/v1/admin/audit`).
- `audit_events` append-only, `outbox_events`, `X-Request-ID`, santé `/health/live` et `/health/ready`.

## 2. Décisions appliquées

| Décision | État d'application |
|---|---|
| D-01 service séparé, AURA via port | Appliqué (`audiobook/`, `StoragePort`) ; intégration/déploiement prod à configurer |
| D-02 modèle MVP | Modèle d'accès/entitlement prêt (free/paid/subscription) ; paiement Lot 3 |
| D-03 identité Google OIDC | Adapter + endpoints présents ; dev-login local uniquement |
| D-04 Stripe + Stripe Tax | Non implémenté (Lot 3) |
| D-05 imports personnels privés | Principe/modèle préparé ; flux import/scan/quota non exposé |
| D-06 offline sans DRM fort | Download refusé ; leases téléchargeables Lot 4 |
| D-07 mondial, modèle droits prêt | Fenêtres/territoires en place ; politique avancée Lot 2 |
| D-08 retrait `/m/{slug}` payant | Nouveau service sécurisé ; migration/retrait effectif du prototype à exécuter |
| D-09 PostgreSQL dédié, migrations | Appliqué (`0001_initial`, `0002_lot1_completion`) |
| D-10 rétention/suppression | Demande de suppression et révocations implémentées ; durées légales/anonymisation/purge sauvegardes à finaliser |
| D-11 3 appareils, 2 sessions, 1 bail | Appliqué (paramétrable) |
| D-12 VPS + sauvegarde/restauration | Hors code ; prérequis avant ouverture payante |

## 3. Exécution et tests

```bash
# Service (local/dev)
export AUDIOBOOK_DSN="postgresql://USER:PASSWORD@HOST:5432/DB"
export AUDIOBOOK_SCHEMA="audiobook"
export AUDIOBOOK_DEV_AUTH=1
export AUDIOBOOK_COOKIE_SECURE=0
export AUDIOBOOK_ADMIN_TOKEN="change-me"
# prod: AURA_API_BASE_URL + AURA_SERVICE_TOKEN (sinon fake storage uniquement en dev)

.venv/bin/python -m uvicorn audiobook.main:create_app --factory --host 0.0.0.0 --port 8080
```

```bash
# Domaine pur
PYTHONPATH=$PWD .venv/bin/python -m pytest tests/audiobook_service/test_domain.py -q

# Domaine + API/intégration PostgreSQL (schéma éphémère)
export AUDIOBOOK_TEST_DSN="postgresql://USER:PASSWORD@HOST:5432/DB"
PYTHONPATH=$PWD .venv/bin/python -m pytest tests/audiobook_service -q
```

Couverture de tests actuelle : domaine, accès/publication/progression, publication 3 pistes, 2 appareils + conflit/takeover/stales/idempotence, limites D-11, suspension, profil/demande de suppression, collections personnelles, catégories/collections éditoriales, audit des décisions/événements.

## 4. Limites et travaux restants avant exposition

- **Intégration/Déploiement** : pas de service Compose intégré ici (ajout séparé recommandé), identité de service AURA à privilèges minimaux, secrets/configuration prod, TLS/cookies sécurisés.
- **D-08** : retirer/migrer l'accès public payant via `/m/{slug}` du prototype AURA, gérer slugs/previews et migration des données/progressions existantes.
- **Auth/admin prod** : désactiver `AUDIOBOOK_DEV_AUTH`, remplacer le token admin bootstrap par un contrôle d'accès conforme (SSO/rôles), rotation/révocation.
- **D-10** : durées légales configurables, anonymisation effective, conservation comptable/fiscale séparée, purge selon cycle de sauvegarde, procédures validées juridiquement.
- **Catalogue/admin** : édition/mise à jour de métadonnées et workflow de validation/états plus riche, validation média avancée, gestion fine des enregistrements/séries selon besoins.
- **Gates** : threat model, inventaire de migration, revue juridique, paiement sandbox avant Lot 3, sauvegarde indépendante + test de restauration avant ouverture payante (D-12).

Les lots 2–5 (droits/territoires avancés, commerce Stripe/Tax, offline/imports complets, recherche/reco/notifications/analytics) restent à implémenter selon `08-delivery-plan-and-risks.md`.
