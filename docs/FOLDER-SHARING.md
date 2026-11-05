# Folder sharing (public links)

Status: **implemented in the API and the web UI; not yet verified on the pilot.**
Creation and revocation require a human session.

Code: `api/folder_shares.py`, routes in `api/main.py`, table `folder_shares`
(`api/schema.sql` + `api/migrations.py`), UI in
`web/src/components/ShareDialog.tsx` (the same dialog creates object and folder
links), API client in `web/src/lib/api.ts`, tests in
`tests/test_folder_shares.py`.

## What it is

A **folder share link** hands a whole folder tree to someone outside AURA,
without an account, a machine token or a storage credential. It reuses the
object-share capability model — one random token, mandatory expiry, immediate
revocation — but a folder contains many files, so the link cannot answer with a
single redirect:

```text
POST   /api/v1/folders/{fid}/share         objects:read, human only  -> mints the link
GET    /api/v1/folders/{fid}/shares        objects:read, human only  -> lists links (no tokens)
DELETE /api/v1/folders/{fid}/shares/{sid}  objects:read, human only  -> revokes immediately
GET    /f/{token}                          public                    -> HTML listing
GET    /f/{token}/o/{oid}                  public                    -> 302 to a presigned GET
```

- `GET /f/{token}` renders a small, no-JavaScript page listing subfolders and
  files. `?d=<folder-id>` opens a subfolder; `?page=<n>` paginates files (100 per
  page). Any id outside the shared subtree answers the same 404 page.
- `GET /f/{token}/o/{oid}` redirects one file to a short-lived presigned S3 URL.
  `?download=1` forces `Content-Disposition: attachment`; otherwise safe types
  (PDF, images, audio, video, plain text) render inline and everything else
  downloads. The page never proxies bytes.
- **Subfolders are always included.** There is no per-link toggle: the semantics
  of sharing a folder are "this folder and everything below it".

## Web UI

Sharing a folder is an action on the folder, next to Rename/Move/Delete in the
folder row menu (`Partager`). It opens the same dialog as a file share, with two
differences:

- the "opening mode" field is absent (each file picks its own safe disposition);
- "Utilisations maximum" becomes **"Téléchargements maximum"**, because a page
  view does not consume a use. Default is unlimited.

The one-time token is displayed once with a copy button; "Liens créés" lists
every link for that folder and can revoke an active one after confirmation. The
list never carries the token, so an existing link cannot be re-displayed.

## Data model

`folder_shares` mirrors `object_shares`:

| Column | Notes |
| --- | --- |
| `id` | UUID v4 |
| `folder_id` | shared folder root. **No foreign key on purpose**: deleting a folder must not be blocked by a link; the row becomes inert and answers 404 |
| `space_id` | copied at creation for tenant attribution and egress metering |
| `created_by`, `created_by_kind` | attribution survives role changes |
| `token_hash` | SHA-256 of the token, unique; the token itself is never stored |
| `expires_at` | mandatory |
| `max_uses`, `use_count` | optional download ceiling, enforced atomically in the `UPDATE` |
| `revoked_at`, `last_used_at`, `created_at` | lifecycle and audit |

Index: `idx_folder_shares_folder(folder_id)`.

## Controls

| Risk | Control |
| --- | --- |
| Catalogue leak replays links | Only the SHA-256 fingerprint is stored |
| Link lives forever | Expiry mandatory; above `AURA_SHARE_TTL_MAX` (30 days) the request is refused, not clamped |
| Link forwarded to a crowd | Optional `max_uses`; each file download consumes one use atomically |
| Recipient crawls the owner's other folders | Every `?d=` folder id is walked up to the shared root; an unknown/foreign id is a 404 |
| Recipient reaches a file outside the tree | The object's `folder_id` must be inside the shared subtree, and the object must be `available` |
| Stored XSS in the public page | Folder/file names are HTML-escaped; CSP `default-src 'none'` (inline CSS only), no scripts, no forms, no external assets |
| Shared file executes script | Inline is limited to `SAFE_INLINE_TYPES` (HTML, SVG, XHTML and unknown types always download) |
| Enumeration of folders/objects/links | Malformed, unknown, expired, exhausted, revoked, foreign and missing all answer the same 404 page |
| Machine token mints durable links | Creation is **human only** |
| CSRF from a hostile page | Mutating calls require `X-CSRF-Token` |
| Caching / referrer / indexing | `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow` on the page and the redirects |
| Silent use | `folder-share-create`, `folder-share-open`, `folder-share-access` (success and denial with a reason) and `folder-share-revoke` are audited with share/folder/object ids, never the token or a URL |

## Operational notes

- The token appears in the request path just like `/s/`; treat access logs as
  credential-adjacent material.
- Deleting a folder does **not** delete its share rows. The link stops resolving
  immediately (404) and the row is kept so audit entries still resolve.
- A soft-deleted object inside a shared folder is listed nowhere and cannot be
  downloaded.
- Downloads from a folder link are metered as `share` egress and increment the
  object's `share_opens` counter, like object-share redemptions. The space
  monthly egress quota is checked before each redirect.
- Routing: the existing `aura-share` Traefik router (priority 200) now covers
  `/f/*` in addition to `/s/*`; `app/nginx.conf` has a `/f/` proxy fallback.

## Deployment and rollback

Normal `api` + `app` rebuild/recreate plus a Traefik label change; it requires
approval because it touches the live pilot host.

1. Deploy the new API image and web bundle.
2. Recreate `api` (and `traefik` if the new `/f/` prefix is not picked up).
3. Verify: `POST /api/v1/folders/{fid}/share` on a test folder returns a token;
   `GET /f/<token>` is `200`; `GET /f/<token>/o/<oid>` is `302` to the S3 host;
   `GET /f/bogus` and an outside `?d=` are `404`; revoke then `404`.

Rollback: remove the `aura-share` router prefix and recreate; existing
`folder_shares` rows are inert without the routes. The table is additive and can
be left in place. Revoke active links first if the feature is withdrawn while
links are in circulation.

## Known limitations

1. **Only folders a human owns can be shared**, same owner-scoping rule as
   objects and folder CRUD.
2. **No internal (AURA-to-AURA) sharing.** The link is anonymous and read-only;
   it grants no account, no session and no permission inside AURA.
3. **No ZIP download.** The listing links to files individually; the API still
   never proxies bytes.
4. **An admin cannot revoke another user's folder links**, because no route
   reaches another user's folders today.
