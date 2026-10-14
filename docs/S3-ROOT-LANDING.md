# Landing page on the S3 root

## Why

`S3_DOMAIN` is an object-storage endpoint, not a website. A browser opening
`https://aura-storage.eurinhash.com/` sends an **unsigned** S3 request
(`ListBuckets`, only `GET /` matches the S3 REST model), and SeaweedFS correctly
answers the XML `AccessDenied` below. Nothing is broken; there is simply no page
behind that host.

```xml
<Error>
  <Code>AccessDenied</Code>
  <Message>Access Denied.</Message>
  <Resource>/</Resource>
</Error>
```

## What the Compose file does about it

The `s3-landing` service (nginx, static HTML) answers that one request with an
explanatory page and a link to the application UI on `APP_DOMAIN`. Its router
matches only an unsigned root `GET`:

```
Host(`${S3_DOMAIN}`) && Path(`/`) && Method(`GET`) && !HeaderRegexp(`Authorization`, `.+`)
```

with an explicit `priority=1000`, above the plain `Host(${S3_DOMAIN})` route that
still sends everything else to SeaweedFS.

## Contract with S3 clients

| Request | Served by | Response |
|---|---|---|
| `GET /` **unsigned** (browser, `curl https://host`) | `s3-landing` | HTML landing page (`200`) |
| `GET /` signed (`aws s3 ls`, SDK `ListBuckets`) | SeaweedFS | S3 XML as before |
| Any `/bucket` or `/bucket/key` request, signed or presigned | SeaweedFS | S3 XML as before |
| `HEAD /`, `OPTIONS /`, other methods on `/` | SeaweedFS | S3 XML as before |

The single behavior change is intentional: an unauthenticated `GET /` returns
`200 text/html` instead of `403` plus XML. S3 clients never send an unsigned
`GET /`, so the API surface is unchanged. No new environment variable is
introduced: the page is rendered from `S3_DOMAIN` and `APP_DOMAIN`, so `.env`
stays the single source of truth.

## Constraints

- The page needs `nginx:1.28.3-alpine`; webfonts are copied from `web/dist/fonts`
  (optional: without them the page falls back to system fonts).
- The server block is static-only: no proxying, no JavaScript, `noindex`,
  CSP `default-src 'none'`, and no access to the internal `storage` network.
- The macros in `landing/index.template.html` are substituted at container start
  by `landing/entrypoint.sh`; the pod never receives real credentials.

## Status

- **VÉRIFIÉ** — `tests/test-landing-routing.sh` (24 checks): router rule, priority,
  unchanged S3 rule, server block, template substitution, entrypoint guards.
- **VÉRIFIÉ** — `docker compose config --quiet` with the local `.env`; page layout
  measured in a headless browser at 1280 and 360 px (no overflow, no clipped text,
  contrast ≥ 5.47:1 for every text role).
- **NON TESTÉ** — live routing, TLS certificate and real Traefik behavior: no
  deployment was performed. After deployment, verify from an external client:

```bash
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' https://aura-storage.eurinhash.com/
curl -sS https://aura-storage.eurinhash.com/ | head -5      # landing page
aws --endpoint-url https://aura-storage.eurinhash.com s3 ls  # must still work
```
