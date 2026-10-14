# AURA API — Authorization matrix and identity model

**Status:** implemented in `api/authz.py`, `api/identity.py`, `api/main.py`; covered by
`tests/test_security_isolation.py` (offline) and exercised end-to-end only after a
pilot deployment. This document is the source of truth for route classification.

## Principals

AURA has two kinds of caller. Every request resolves to exactly one principal.

| Principal | Authenticates with | CSRF | Capabilities |
|---|---|---|---|
| **user** (human) | HttpOnly `aura_session` cookie | required on non-GET | role map below |
| **service** (machine-to-machine) | `Authorization: Bearer aura_<id>_<secret>` | not applicable | explicit scopes stored on the identity |

A service identity is scoped to one space and one application/environment. It never
uses a human session cookie, and cookie auth is never accepted for a service.

### Roles (human users)

Default-deny: a role only holds the capabilities listed here; anything else is refused.

| Capability | `user` | `operator` | `admin` |
|---|:--:|:--:|:--:|
| `objects:read` | ✅ | ✅ | ✅ |
| `objects:write` | ✅ | ✅ | ✅ |
| `objects:delete` | ✅ | ✅ | ✅ |
| `objects:purge` | ❌ | ✅ | ✅ |
| `admin:read` | ❌ | ✅ | ✅ |
| `admin:write` | ❌ | ❌ | ✅ |

### Capabilities (service identities)

Service identities are granted a subset of the six capabilities above; the minimum
set should be requested (e.g. a read-only consumer gets only `objects:read`).

## Route matrix

| Method | Route | Capability | Notes |
|---|---|---|---|
| GET | `/health/live` | public | liveness only |
| GET | `/health/ready` | public | does not leak backend details |
| POST | `/api/v1/login` | public | rate-limited per client IP |
| POST | `/api/v1/logout` | authenticated **human** + CSRF | deletes the session |
| GET | `/api/v1/me` | authenticated | principal metadata |
| GET | `/api/v1/objects` | `objects:read` | scoped to space (+ owner for humans) |
| GET | `/api/v1/objects/{oid}` | `objects:read` | 404 if outside the caller's scope |
| POST | `/api/v1/objects/upload-intents` | `objects:write` | server picks the object key |
| POST | `/api/v1/objects/{oid}/commit` | `objects:write` | streaming SHA-256, idempotent |
| POST | `/api/v1/objects/{oid}/download-intent` | `objects:read` | presigned GET, scoped |
| DELETE | `/api/v1/objects/{oid}` | `objects:delete` | soft delete |
| POST | `/api/v1/objects/{oid}/purge` | `objects:purge` | destructive, operator/admin |
| POST | `/api/v1/admin/reconcile` | `admin:write` | global sweep of stale intents |
| GET | `/api/v1/admin/stats` | `admin:read` | aggregate counts, no content |
| POST/GET | `/api/v1/admin/applications` | `admin:write` / `admin:read` | platform registry |
| POST/GET | `/api/v1/admin/spaces` | `admin:write` / `admin:read` | space + default bucket |
| POST/GET | `/api/v1/admin/identities` | `admin:write` / `admin:read` | M2M identities |
| POST | `/api/v1/admin/identities/{iid}/rotate` | `admin:write` | returns a new token once |
| POST | `/api/v1/admin/identities/{iid}/revoke` | `admin:write` | immediate revocation |

A route that is not classified here is **closed**: `tests/test_security_isolation.py`
asserts that every `/api/v1` route rejects anonymous callers (401/403/422/405).

## Isolation rules

- An object always carries `space_id` (and `application_id`, `environment`). Every
  catalogue query is filtered by the caller's space.
- Human users are additionally filtered by `owner_id`: they only see their own
  objects inside their space.
- Service identities see the whole space they are bound to, and nothing else.
- The **object key is always generated server-side** (`aura/<space>/<actor>/<uuid>`).
  Client-supplied `object_key`, `owner_id`, `space_id` fields are rejected (422).
- The **bucket is never client-chosen**: the caller's space has a registered bucket
  allow-list; an unregistered bucket is refused (403).
- Tenant/application/space identifiers received in a request never grant access.
- 401 (not authenticated) and 403 (not permitted) never reveal whether an object
  exists; cross-scope reads return 404.

## Provisioning, rotation and revocation

Admin-only, via the API (no direct database editing required):

1. **Application** — `POST /api/v1/admin/applications {name}`.
2. **Space** — `POST /api/v1/admin/spaces {application_id, name, environment,
   default_bucket?}`. A dedicated bucket is registered for the space.
3. **Identity** — `POST /api/v1/admin/identities {space_id, name, scopes,
   ttl_seconds?}`. The response contains the token **exactly once**; store it in the
   consuming platform's secret manager. AURA keeps only the SHA-256 fingerprint.
4. **Rotate** — `POST /api/v1/admin/identities/{id}/rotate`; the previous secret stops
   working immediately and the new token is returned once.
5. **Revoke** — `POST /api/v1/admin/identities/{id}/revoke`; access stops immediately.
6. **Audit** — creation, rotation, revocation and every authenticated action are
   recorded in the JSON-lines audit log by identity ID, never by secret.

Never place a token in logs, tickets, chat, the frontend bundle, or this repository.

## Secret handling

- Tokens are `aura_<uuid>_<64-hex>`; only `sha256(secret)` is stored.
- Comparison is constant-time; unknown, revoked and expired tokens all yield 401.
- Failed machine authentication is rate-limited per client IP (default 60/60s).
- Login for humans is rate-limited per client IP (default 10/60s).
