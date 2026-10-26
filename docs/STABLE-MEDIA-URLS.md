# Stable media URLs for a course site

AURA does **not** issue permanent public URLs, by design:

- share links expire (30 days max) and are revocable;
- the redirect they return points to a presigned S3 URL valid for
  `AURA_SHARE_PRESIGN_TTL` (60 s by default);
- session intents (`download-intent`, `preview-intent`) are valid for
  `AURA_INTENT_TTL` (900 s by default).

So "permanent on my course site" must be implemented **on the course site**:
one stable URL you own, backed by short-lived AURA URLs that are minted again
when needed. AURA stays the private master copy; the course platform decides who
may watch.

## Pattern A — stable redirect, server-side (recommended)

```text
https://cours.example.com/media/lecture-12      <- permanent, indexed, in your HTML
        |  302 no-store
        v
your backend (M2M identity, objects:read)
        |  POST /api/v1/objects/{oid}/preview-intent    (cached, inline)
        v
https://storage.example.com/bucket/key?X-Amz-...        <- 15 min, rotates
```

```js
// Node/Express sketch. AURA_TOKEN is a service identity (Bearer), read-only,
// scoped to one space, stored server-side only.
const cache = new Map(); // oid -> { url, expiresAt }

app.get("/media/:oid", async (req, res) => {
  const oid = req.params.oid;
  const now = Date.now();
  let hit = cache.get(oid);
  if (!hit || hit.expiresAt - now < 120_000) {
    const r = await fetch(`${AURA}/api/v1/objects/${oid}/preview-intent`, {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.AURA_TOKEN}` },
    });
    if (!r.ok) return res.sendStatus(r.status === 404 ? 404 : 502);
    const body = await r.json();
    hit = {
      url: body.preview_url,
      expiresAt: (body.expires_at ?? Math.floor(now / 1000) + 900) * 1000,
    };
    cache.set(oid, hit);
  }
  res.set("Cache-Control", "no-store").redirect(302, hit.url);
});
```

```python
# FastAPI sketch (same idea).
@app.get("/media/{oid}")
def media(oid: str, request: Request):
    hit = cache.get(oid)
    if not hit or hit["expires_at"] - time.time() < 120:
        r = httpx.post(f"{AURA}/api/v1/objects/{oid}/preview-intent",
                       headers={"Authorization": f"Bearer {AURA_TOKEN}"})
        if r.status_code == 404:
            raise HTTPException(404)
        r.raise_for_status()
        body = r.json()
        hit = {"url": body["preview_url"],
               "expires_at": body.get("expires_at") or time.time() + 900}
        cache[oid] = hit
    return RedirectResponse(hit["url"], status_code=302,
                            headers={"Cache-Control": "no-store"})
```

Why `preview-intent` and not a share link:

- `preview-intent` serves the object inline with its own type (needed for `<video>`),
  and a machine identity with `objects:read` may call it; a share link cannot be minted
  by a machine identity at all (human-only by design);
- no CSRF header is needed with a Bearer token;
- no per-object share row is accumulated for each course;
- the URL can be refreshed transparently, so the public URL never changes.

### Sizing the TTL

The browser follows the 302 once per media resource and then issues Range
requests to the final S3 URL. If playback lasts longer than the presigned
lifetime, a later seek/segment can receive `403`:

- set `AURA_INTENT_TTL` to at least the longest continuous viewing session
  (e.g. 6 h = 21600) **or** keep it short and accept that very long sessions
  may need a reload;
- never set it above what a leaked URL should stay valid — it is a bearer URL;
- `AURA_INTENT_TTL` is global: raising it lengthens every intent (preview and
  download), including ordinary user downloads. Decide deliberately.
- Use `download-intent` instead of `preview-intent` for files that must
  download rather than play.

### Caching and rate limits

- Cache the minted URL until ~2 min before `expires_at`; otherwise every viewer
  hits AURA and burns latency (each intent also runs an integrity `HEAD`).
- M2M calls are rate-limited (`AURA_M2M_RATE_LIMIT`, 60/min per identity by
  default): per-viewer minting will exhaust it; a cache avoids that.
- Send `Cache-Control: no-store` on the redirect, not on the media if you want
  the browser to buffer normally.

## Next.js (App Router) reference route

The trust relationship is a **service identity per site**: the Next.js server
holds `aura_<id>_<secret>`, the browser never sees it. Create it in
**Administration → Intégrations** (one partner site = metadata + dedicated
identity, `scopes: ["objects:read"]`, optional key expiry and media TTL). Store
the token as a server-only env var; rotate it from the same tab (the old secret
dies immediately) or via `POST /api/v1/admin/identities/{id}/rotate`.

```ts
// app/media/[oid]/route.ts
import { NextRequest } from "next/server";
// import { auth } from "@/auth"; // your entitlement check

export const runtime = "nodejs";        // keep the secret server-side
export const dynamic = "force-dynamic";

const AURA = process.env.AURA_API_BASE!;     // e.g. https://app.example.com
const TOKEN = process.env.AURA_API_TOKEN!;   // aura_<id>_<secret>, never NEXT_PUBLIC_

type Cached = { url: string; expiresAt: number };
const cache = new Map<string, Cached>();     // per instance: use Redis/KV if scaled

async function mint(oid: string): Promise<Cached> {
  const res = await fetch(`${AURA}/api/v1/objects/${oid}/preview-intent`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}` },
    cache: "no-store",
  });
  if (!res.ok) {
    throw Object.assign(new Error(`aura ${res.status}`), { status: res.status });
  }
  const body = await res.json();
  return {
    url: body.preview_url,
    expiresAt: (body.expires_at ?? Math.floor(Date.now() / 1000) + 900) * 1000,
  };
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ oid: string }> }, // Next 15: params is a Promise
) {
  const { oid } = await params;

  // 1. Authorize the STUDENT here (session, enrolment, subscription).
  // const session = await auth(); if (!session) return new Response(null, { status: 401 });
  // 2. Verify the student's course owns `oid` (your DB, not AURA).

  let hit = cache.get(oid);
  if (!hit || hit.expiresAt - Date.now() < 120_000) {
    try {
      hit = await mint(oid);
      cache.set(oid, hit);
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 404) return new Response("not found", { status: 404 });
      if (status === 429)
        return new Response("busy", { status: 503, headers: { "Retry-After": "5" } });
      if (status === 401 || status === 403)
        return new Response("integration misconfigured", { status: 502 });
      return new Response("storage unavailable", { status: 502 });
    }
  }

  return new Response(null, {
    status: 302,
    headers: { Location: hit.url, "Cache-Control": "no-store" },
  });
}
```

Then the permanent course URL is simply
`https://cours.example.com/media/<oid>` in `<video src>`.

Notes for Next.js specifically:

- **Never** prefix the token with `NEXT_PUBLIC_`, never read it in a Client
  Component, never accept an object id without checking the student's course.
- Module-level `Map` caching is per serverless instance: with many lambdas, use
  Redis/Upstash keyed by `oid` (value: URL + `expires_at`).
- A 302 is cheap and streams nothing through your function; do not proxy bytes
  unless you accept the bandwidth and timeout cost.
- If the hosting platform caps response time, a `302` is unaffected; only a
  proxy would be.
- Add `Referrer-Policy: no-referrer` on the pages that embed the media.

### "Unlimited" stops at three places

| Limit | Reality | Mitigation |
| --- | --- | --- |
| API calls | M2M identity: 60 req/min (`AURA_M2M_RATE_LIMIT`) | cache minted URLs |
| Signed URL lifetime | `AURA_INTENT_TTL`, 900 s default | raise it to the longest lesson, or refresh and accept a reload |
| Long playback | the player keeps the final S3 URL; a `403` can appear after expiry | TTL ≥ session length, or a CDN mirror |

The **key** gives your server unlimited, non-interactive access within its
scopes. It never makes the *media URL* permanent: that indirection is the whole
point, and it is what keeps revocation possible.

## Pattern B — static site, scheduled rotation (fallback)

If the course page is purely static (no backend), the only option is to
regenerate the embedded share link before it expires:

- shares last at most 30 days and require a human session to mint;
- a scheduled job must log in (admin/operator account + CSRF) every few days,
  revoke the previous link and rewrite the page;
- the page's URL stays stable, but the token inside changes, and any copy of the
  old HTML keeps working until its expiry.

This is operationally fragile. Prefer Pattern A or C.

## Pattern C — CDN mirror for truly public course material

If the media is public and permanent (no revocation requirement), do not use
AURA share links as a CDN:

- publish it to the course platform / CDN, which gives a permanent URL, range
  support and edge caching;
- keep AURA as the private master and re-publish on change.

Share links are capabilities for **controlled** access, not a public hosting
product. They also carry per-redemption cost (audit row, DB update, integrity
HEAD).

## Access control belongs on the course site

Once a stable URL exists, anyone who can reach it can fetch the media. Put
authentication/authorization (enrolment, subscription, SSO) in front of the
`/media/*` route, not in AURA. AURA's M2M identity only proves *your backend*
may read the space.

## Operational checklist

- [ ] One service identity per course site, `objects:read` only, scoped to its space.
- [ ] Bearer token in a secret manager, never in the browser bundle.
- [ ] `/media/:oid` checks the viewer's course entitlement before redirecting.
- [ ] Intent URLs cached until `expires_at - 2 min`.
- [ ] `AURA_INTENT_TTL` sized to the longest lesson, and documented.
- [ ] Rotate the M2M token on staff changes; revoke the identity to cut access.
- [ ] Monitor AURA 403/429 on the mint route (expiry and rate limit).
- [ ] `Referrer-Policy: no-referrer` on course pages that embed media.
