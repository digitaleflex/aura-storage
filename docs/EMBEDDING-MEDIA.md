# Embedding AURA media on another site

Status: **supported through share links; no CORS, no partner account.**
Scope: `<img>`, `<audio>`, `<video>` and PDF `<iframe>` on a partner site.
Non-goals: calling `/api/v1` from the partner's browser (no CORS), canvas pixel
access, HLS/DASH transcoding.

## Flow

1. **Mint a link server-side** (human session; machine identities cannot mint):

   ```http
   POST /api/v1/objects/{oid}/share
   Content-Type: application/json
   X-CSRF-Token: <session csrf>

   {"expires_in": 604800, "max_uses": null, "content_disposition": "inline"}
   ```

   `expires_in` is mandatory in practice and capped at `AURA_SHARE_TTL_MAX`
   (30 days by default). The response carries `url` (absolute when
   `AURA_SHARE_BASE_URL` is set, otherwise `/s/<token>`) and `token`, **shown
   once**. Store it server-side; the catalogue keeps only its SHA-256
   fingerprint.
2. **Use the URL as a media source.** Each load is
   `GET /s/<token>` → `302` to a presigned S3 GET valid for
   `AURA_SHARE_PRESIGN_TTL` (60 s) → bytes come from the storage host, never
   through the API.
3. **Revoke** with `DELETE /api/v1/objects/{oid}/shares/{sid}` when the
   embedding period ends.

## Snippets

```html
<img src="https://app.example.com/s/TOKEN" alt="Rapport" referrerpolicy="no-referrer">

<video src="https://app.example.com/s/TOKEN" controls playsinline
       preload="metadata" referrerpolicy="no-referrer"></video>

<audio src="https://app.example.com/s/TOKEN" controls preload="metadata"
       referrerpolicy="no-referrer"></audio>

<!-- PDF only: inline rendering is refused for HTML/SVG/XHTML. -->
<iframe src="https://app.example.com/s/TOKEN" title="PDF"
        sandbox="allow-same-origin allow-popups"
        referrerpolicy="no-referrer"></iframe>
```

Use the app hostname in `src`, not the storage host: the token is the credential
and the API decides the type and disposition. Do not add `crossorigin` unless
you actually need CORS (canvas/WebGL); it would turn a working `<video>` into a
blocked fetch.

## Partner-side Content-Security-Policy

Allow both origins the navigation passes through — the app origin for `/s/`,
then the storage origin after the redirect:

```text
img-src   'self' https://app.example.com https://storage.example.com;
media-src 'self' https://app.example.com https://storage.example.com;
frame-src https://app.example.com https://storage.example.com;
```

No `script-src`, `connect-src` or CORS entry is needed for playback.

## What AURA guarantees

| Property | Behaviour |
| --- | --- |
| Redirect caching / indexing | `302` with `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow`, `X-Content-Type-Options: nosniff` |
| Streaming / seeking | HTTP Range: `206 Partial Content`, `Accept-Ranges: bytes` (verified live) |
| Type safety | `inline` only for PDF, images (except SVG), plain text, audio and video; HTML/SVG/XHTML and unknown types are `attachment` |
| Revocation | New redemptions answer `404` immediately; an S3 URL already issued stays valid for at most 60 s |
| Use ceiling | `max_uses` is enforced atomically at redemption; every redemption counts |
| Audit | `share-create`, `share-access` (success/denied with a reason) and `share-revoke` are recorded by share id, never by token |
| Enumeration | Unknown, malformed, expired, exhausted and revoked links all answer the same `404` |

## Precautions

- **The token is a secret in your HTML.** Anyone who reads the page can use the
  link until it expires or is revoked. Do not put it in analytics, logs of the
  partner app, or a page cached by a CDN. Keep `referrerpolicy="no-referrer"`.
- **Use short expiries and unlimited uses for embeds.** A media player can
  restart a stream and redeem the link again; `max_uses: 1` is for one-shot
  downloads, not playback. Recommend 1 h–7 d with `max_uses: null`.
- **Re-mint per viewer or per session** from your backend; never bake a
  long-lived token into a static page.
- **Edge logs contain the token in the path.** AURA's access logs drop query
  strings (`X-Amz-Signature` never appears) but the `/s/<token>` path is logged.
  Treat proxy logs as sensitive and keep link lifetimes short.
- **No transcoding, no poster, no thumbnails.** The browser must support the
  file's codecs; an unsupported codec shows an empty player.
- **`AURA_SHARE_BASE_URL`** should name the public app origin so the API returns
  absolute URLs. Without it, resolve the relative `/s/<token>` against the app
  origin in your backend.
- **CORS stays closed.** Media elements work without it. `fetch()`, XHR or
  canvas reads from the partner origin are blocked (API has no CORS; the S3
  gateway allows only the app origin).

## Verified 2026-10-26 (pilot)

- PDF share with `inline`: `/s/<token>` → `302`; storage GET with
  `Range: bytes=0-0` → `206`, `Content-Disposition: inline`,
  `Content-Type: application/pdf`, no `X-Frame-Options` → iframe-embeddable.
- Video share with `inline` (temporary 20-byte mp4 uploaded, then purged):
  mint `200`, `/s/<token>` → `302`, storage `Range: bytes=0-3` → `206`
  `Content-Disposition: inline`, `Content-Type: video/mp4`,
  `Content-Range: bytes 0-3/20` → `<video>` can stream and seek.
- Non-inline object shared as `attachment`: storage answers `206` with
  `Content-Disposition: attachment`.
- S3 CORS: `Access-Control-Allow-Origin` echoed for the app origin only; absent
  for a foreign origin. API `/api/v1` has no CORS middleware.
