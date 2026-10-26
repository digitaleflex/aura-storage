# Object sharing (public links)

Status: **implemented in the API and in the web UI, deployed and verified live on the pilot (2026-10-26).** Creation/revocation require a human session.
Code: `api/shares.py`, routes in `api/main.py`, table `object_shares`
(`api/schema.sql`), UI in `web/src/components/ShareDialog.tsx` (+ helpers in
`web/src/lib/shares.ts`), tests in `tests/test_object_shares.py` and
`web/e2e/shares.spec.ts`.

## What it is

A **share link** hands exactly one object to someone outside AURA, without an
account, a machine token or a long-lived URL. It is the only unauthenticated
route that leads to object bytes.

```text
POST   /api/v1/objects/{oid}/share        objects:read, human only  -> mints the link
GET    /api/v1/objects/{oid}/shares       objects:read              -> lists links (no tokens)
DELETE /api/v1/objects/{oid}/shares/{sid} objects:read, human only  -> revokes immediately
GET    /s/{token}                         public                    -> 302 to a presigned GET
```

Typical use:

```bash
# 1. mint (session cookie + CSRF header, as for any mutating call)
curl -X POST https://app.<domain>/api/v1/objects/$OID/share \
  -b "aura_session=$SESSION" -H "X-CSRF-Token: $CSRF" \
  -H 'content-type: application/json' \
  -d '{"expires_in": 172800, "max_uses": 1, "content_disposition": "attachment"}'
# -> { "id": ..., "token": "...", "url": "https://app.<domain>/s/...", ... }

# 2. the recipient just opens the url; every redemption is audited
curl -sI https://app.<domain>/s/<token> | grep -i '^location'
```

## Web UI

No new navigation tab: sharing is an action on a file, so it lives where the
file is.

- **Entry points**: `Partager` in the row menu and in the details drawer, for
  an `available` object and a human session only (the server refuses machine
  identities). Service accounts never see it.
- **Dialog** (`web/src/components/ShareDialog.tsx`): duration (1 h, 24 h, 7 d,
  30 d), maximum uses (unlimited, 1, 5, 25) and opening mode. "Afficher dans le
  navigateur" is offered only for the server's safe inline types (PDF, JPEG,
  PNG, WebP, GIF, plain text, audio and video); HTML, SVG, XHTML and unknown
  types are shared as downloads, mirroring `SAFE_INLINE_TYPES` in
  `api/shares.py`.
- **One-time link**: the token is returned once, so the freshly created URL is
  displayed in a read-only field with a copy button and a warning that it will
  not be shown again. The API's relative `/s/<token>` is resolved against the
  app origin when `AURA_SHARE_BASE_URL` is unset.
- **Revocation**: "Liens créés" lists every link for that object (state, uses,
  expiry) and revokes an active one after an explicit confirmation. Listed
  links never carry their token, so they cannot be re-displayed — only revoked.
- **Routing**: `aura-share` (Traefik, priority 200) sends `/s/*` straight to the
  API; `app/nginx.conf` keeps a `/s/` proxy as a fallback so a dropped router
  cannot turn links into `index.html`.

## Live verification — 2026-10-26 (pilot)

Run with the deployed UI/API, a human admin session and one temporary link on an
existing object. No token, presigned URL or credential was printed.

| Step | Result |
| --- | --- |
| Mint (`expires_in` 3600, `max_uses` 1, `attachment`) | `200` |
| `GET /s/<token>` without following the redirect | `302` to the S3 host |
| `GET /objects/{oid}/shares` | `use_count=1`, `active=false` (exhausted) |
| `DELETE /objects/{oid}/shares/{sid}` | `200` |
| `GET /s/<token>` after revocation | `404` |
| Served web bundle | deploy postflight hash match with `web/dist` |

The temporary share row remains in the catalogue as revoked/exhausted (its
history is never rewritten); the object's bytes were only read.

## What it is not

- **Not a proxy.** The API never streams bytes: redemption answers `302` to a
  presigned S3 URL valid for `AURA_SHARE_PRESIGN_TTL` (60 s). The link therefore
  carries no S3 credential, and the storage path is unchanged.
- **Not a public bucket.** It is one capability per object, always expiring, and
  revocable. Nothing becomes listable or discoverable: tokens are 256-bit random
  values and failures are indistinguishable.
- **Not a permission grant inside AURA.** The recipient has no identity, no
  session and no access to anything else.

## Controls

| Risk | Control |
| --- | --- |
| Catalogue leak replays links | Only the SHA-256 fingerprint of the token is stored |
| Link lives forever | Expiry is mandatory; above `AURA_SHARE_TTL_MAX` (30 days) the request is refused, not clamped |
| Link forwarded to a crowd | `max_uses` is enforced inside the redemption `UPDATE` (atomic), so concurrent redemptions cannot exceed it |
| Recipient keeps access after the fact | `DELETE .../shares/{sid}` takes effect on the next redemption, is idempotent, and is audited |
| Enumeration of objects/shares | Unknown, malformed, expired, exhausted and revoked all answer the same `404` |
| Machine token mints durable links | Creation is **human only**: a leaked M2M token must not create links that outlive its own revocation |
| CSRF from a hostile page | Mutating calls still require `X-CSRF-Token` |
| Stored XSS via a shared file | `inline` is refused for `text/html`, `image/svg+xml`, XHTML, etc.; default is `attachment` |
| Caching / referrer / indexing of the redirect | `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow` |
| Brute force / scraping | 256-bit tokens make guessing irrelevant; the route is rate-limited at the edge (`api-ratelimit`) |
| Silent use | `share-create`, `share-access` (success and denial with a reason) and `share-revoke` are audited with `share_id` and `object_id`, never the token or the URL |

## Operational notes

- **The token appears in the request path**, so it lands in Traefik/nginx access
  logs exactly like a presigned URL does today. Treat access logs as
  credential-adjacent material, or turn path logging off for `/s/` if that
  matters for your threat model.
- Links are **not** deleted when they expire: the row stays so audit entries keep
  resolving. Only `objects:purge` removes them, together with the object.
- Revocation is per link. Closing an account does not revoke the links it created
  — revoke them before off-boarding, or purge the objects.
- A soft-deleted object (`status = deleted`) stops resolving immediately; the
  share stays listed as inactive.

## Known limitations

1. **Only objects a human owns can be shared.** Object visibility is owner-scoped
   for humans (`_object_scope`), so an operator cannot mint a link for an object
   ingested by a service identity (`owner_id IS NULL`). Lifting this is an
   authorization decision — either space-scoped human visibility or a new
   `objects:share` capability for machines — and is **not** done here.
2. **An admin cannot revoke another user's links**, for the same reason: no admin
   route reaches another user's objects today.
3. **No UI yet.** The web client does not expose sharing; the API and the links
   are usable as documented above.

## Deployment and rollback

Deployment is a normal `api` recreation plus a Traefik label change; it requires
approval because it touches a live pilot host.

1. `docker compose up -d --force-recreate --no-deps api` (builds nothing new —
   the image must be rebuilt first if the code is not already in it).
2. Recreate `traefik` only if the new `aura-share` router label is not picked up
   (it lives on the `api` service, so recreating `api` is normally enough; note
   the known ~30 s edge window when Traefik restarts).
3. Verify: `GET /s/<token>` → `302` with a `Location` on the S3 host;
   `GET /s/bogus` → `404`; expiry/revocation → `404`; `app` and S3 untouched.

Rollback: remove the `aura-share` router label (or the whole feature) and
recreate `api`. Existing `object_shares` rows are inert without the route; the
table is additive and needs no migration to be left in place. Revoke active
links first if the feature is withdrawn while links are in circulation.
