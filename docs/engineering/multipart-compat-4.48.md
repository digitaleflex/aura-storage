# SeaweedFS 4.48 — multipart / presigned-part / SSE / Range compatibility

Gate for **issue #84 / [ENG-03]** and the *« Gate de compatibilité »* wording:
*« Vérifier sur la version SeaweedFS épinglée : CreateMultipartUpload, UploadPart,
ListParts, CompleteMultipartUpload, AbortMultipartUpload, URLs présignées par
partie, limites et checksums. Ne pas supposer une compatibilité identique à AWS
S3. »*

**Result: every asserted point was reproduced against the pinned image. One
operational sub-question (physical disk reclaim after abort) stays UNKNOWN and is
flagged as such. No assumed results.**

## 1. Exact artifact under test

| Field | Value |
|---|---|
| Image tag | `chrislusf/seaweedfs:4.48` |
| Image ID (sha256) | `sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d` |
| Repo digest | `chrislusf/seaweedfs@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d` |
| Image created | `2026-09-28T18:41:21.744952814Z` |
| Test date | 2026-10-20 |
| Harness | `tests/multipart-compat-4.48.sh` + `tests/multipart_compat_client.py` (additive) |

The stack run was **ephemeral and isolated**: its own docker network
(`compat-4-48-net`), its own container names (`compat-4-48-*`), data under
`/tmp/opencode/compat-4-48-*`, a **throwaway** `s3.json` with generated
credentials, a generated throwaway `WEED_S3_SSE_KEK`, and an ephemeral host port
(`docker run -p 127.0.0.1::8333`). It never referenced the pilot stack
(`aura-001-*` / compose project `aura-storage`) and never read the pilot `.env`.
The whole stack is removed by the harness trap (containers, network, workdir).

## 2. Exact commands run

```bash
# 1. Confirm the pinned image (digest recorded above)
sg docker -c 'docker image inspect chrislusf/seaweedfs:4.48'

# 2. Run the harness (it starts/stops the ephemeral stack itself)
sg docker -c 'bash tests/multipart-compat-4.48.sh'
```

The harness internally runs (credentials/KEK/port generated per run):

```bash
docker network create compat-4-48-net
docker run -d --name compat-4-48-master --network compat-4-48-net \
  -v "$WORK/master:/data" chrislusf/seaweedfs:4.48 master \
  -ip=compat-4-48-master -ip.bind=0.0.0.0 -mdir=/data
docker run -d --name compat-4-48-volume --network compat-4-48-net \
  -v "$WORK/volume:/data" chrislusf/seaweedfs:4.48 volume \
  -master=compat-4-48-master:9333 -ip=compat-4-48-volume -ip.bind=0.0.0.0 \
  -dir=/data -port=8080 -max=0
docker run -d --name compat-4-48-filer --network compat-4-48-net -p 127.0.0.1::8333 \
  -e WEED_S3_SSE_KEK='<throwaway 64-hex>' \
  -v "$WORK/filer:/data" -v "$WORK/s3.json:/etc/seaweedfs/s3.json:ro" \
  chrislusf/seaweedfs:4.48 filer \
  -master=compat-4-48-master:9333 -ip=compat-4-48-filer -ip.bind=0.0.0.0 -port=8888 \
  -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json \
  -s3.allowedOrigins=https://compat.example.test
# then, against the ephemeral endpoint:
S3_ACCESS_KEY=... S3_SECRET_KEY=... .venv/bin/python tests/multipart_compat_client.py \
  --endpoint http://127.0.0.1:<ephemeral> --bucket compat-<random> \
  --origin https://compat.example.test --volume-container compat-4-48-volume
```

Signing is done with boto3 (`signature_version="s3v4"`, path-style), the **same
library and configuration `api/s3.py` uses**. Presigned URLs are then *consumed*
with plain `urllib` — i.e. what a browser does, not an SDK. No hand-written SigV4
was needed. `api/s3.py` currently presigns only `put_object`/`get_object`; it does
**not** presign `upload_part`, so a future server endpoint is required for
browser-side multipart (see §5).

## 3. Raw outputs (trimmed but unedited) — final run

```
=== EPHEMERAL STACK (image chrislusf/seaweedfs:4.48) ===
image id: sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d  digest: chrislusf/seaweedfs@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d  created: 2026-09-28T18:41:21.744952814Z
endpoint: http://127.0.0.1:32769 (ephemeral host port)
gateway reachable (HTTP 403 on root)
[PASS] CreateBucket compat-688dbed5bb59

=== POINT 1: CreateMultipartUpload / UploadPart / ListParts / CompleteMultipartUpload / AbortMultipartUpload ===
[PASS] CreateMultipartUpload -> UploadId present=True
[INFO] create response keys: ['Bucket', 'Key', 'ResponseMetadata', 'UploadId']
[PASS] UploadPart x2 -> ETag1='"3c484266f9315485694556e6c693bfa2"' ETag2='"4c547f435fd36f510bdac9ee7971b023"'
[INFO] ListParts -> [(1, '"3c484266f9315485694556e6c693bfa2"', 5242880), (2, '"4c547f435fd36f510bdac9ee7971b023"', 1048576)]
[PASS] ListParts reports both parts
[INFO] CompleteMultipartUpload -> ETag='"06f45652520586381550a3e2968b4eaf-2"' Location='http://127.0.0.1:32769/compat-688dbed5bb59/compat/point1.bin'
[INFO] HEAD -> ContentLength=6291456 ETag='"06f45652520586381550a3e2968b4eaf-2"'
[PASS] HEAD ContentLength matches sum of parts
[PASS] GET round-trip SHA-256 matches
[PASS] AbortMultipartUpload accepted
[PASS] ListParts after abort is gone (Code='NoSuchUpload' Message='The specified multipart upload does not exist. The upload ID may be invalid, or the upload may have been aborted or completed.' HTTPStatus=404)

=== POINT 2: minimum-part-size rule (non-last part < 5 MiB) ===
[INFO] UploadPart of two 1 MiB parts succeeded; now attempting Complete ...
[PASS] Complete rejected small non-last part: Code='EntityTooSmall' Message='Your proposed upload is smaller than the minimum allowed object size.' HTTPStatus=400
[INFO] no object at the key after rejected Complete (NoSuchKey)

=== POINT 3: presigned per-part URL via plain HTTP client (urllib) ===
[INFO] presigned upload_part URL: http://127.0.0.1:32769/compat-688dbed5bb59/compat/point3-presigned.bin?<X-Amz-Algorithm,X-Amz-Credential,X-Amz-Date,X-Amz-Expires,X-Amz-Signature,X-Amz-SignedHeaders,partNumber,uploadId>
[PASS] plain-HTTP PUT of part 1 via presigned URL -> HTTP 200 ETag='"3c484266f9315485694556e6c693bfa2"'
[PASS] plain-HTTP PUT of part 2 via presigned URL -> HTTP 200 ETag='"4c547f435fd36f510bdac9ee7971b023"'
[PASS] CompleteMultipartUpload with exact returned ETags -> ETag='"06f45652520586381550a3e2968b4eaf-2"'
[PASS] presigned-part upload round-trip SHA-256 matches

=== POINT 4: ServerSideEncryption=AES256 on multipart ===
[INFO] single PUT HEAD ServerSideEncryption='AES256'
[PASS] single PUT with SSE-S3 reports AES256 (KEK active)
[INFO] CreateMultipartUpload response ServerSideEncryption=None
[INFO] CreateMultipartUpload did not echo SSE (SeaweedFS may apply it server-side anyway; HEAD after Complete is the authoritative check)
[INFO] UploadPart 1 WITH x-amz-server-side-encryption (unsigned) -> HTTP 403 body=b'<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>SignatureDoesNotMatch</Code>...'
[INFO] UploadPart 1 WITHOUT SSE header -> HTTP 200 ETag='"3c484266f9315485694556e6c693bfa2"'
[INFO] UploadPart 2 WITHOUT SSE header -> HTTP 200 ETag='"4c547f435fd36f510bdac9ee7971b023"'
[INFO] SSE header REJECTED on UploadPart when unsigned -> the SSE-S3 header must NOT be re-sent on a presigned UploadPart (see doc)
[PASS] UploadPart without the SSE header succeeds (header not required per part)
[PASS] CompleteMultipartUpload (SSE at create) -> ETag='"06f45652520586381550a3e2968b4eaf-2"'
[INFO] HEAD after Complete x-amz-server-side-encryption='AES256'
[PASS] HEAD after Complete reports AES256 (multipart inherited SSE)
[PASS] SSE multipart download bytes match uploaded SHA-256

=== POINT 5: byte-range GET ===
[INFO] full GET -> HTTP 200 ContentLength=6291456 Accept-Ranges='bytes'
[PASS] full GET returns whole object
[INFO] Range 0-99 -> HTTP 206 Content-Range='bytes 0-99/6291456' ContentLength=100 Accept-Ranges='bytes'
[PASS] prefix range returns 206 with 100 bytes
[INFO] suffix Range -50 -> HTTP 206 Content-Range='bytes 6291406-6291455/6291456'
[PASS] suffix range returns last 50 bytes
[INFO] out-of-range -> HTTP 416 Content-Range='bytes */6291456' body=b'<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>InvalidRange</Code><Message>The requested range is not satisfiable</Message>...'
[PASS] out-of-range range returns 416
[INFO] multi-range -> HTTP 200 Content-Type='application/octet-stream' contains-first=True contains-second=True len=6291456

=== POINT 6: abort cleanup ===
[INFO] volume /data stats (files,bytes) before upload: (4, 22029799)
[INFO] volume /data stats after 2x5MiB parts: (4, 27279455)
[INFO] ListMultipartUploads before abort -> ['compat/point6-cleanup.bin']
[PASS] AbortMultipartUpload accepted
[PASS] ListParts after abort gone (Code='NoSuchUpload' Message='The specified multipart upload does not exist. The upload ID may be invalid, or the upload may have been aborted or completed.' HTTPStatus=404)
[INFO] ListMultipartUploads after abort -> []
[INFO] volume /data stats after abort: (4, 27279455)
[INFO] volume bytes: before=22029799 after_upload=27279455 after_abort=27279455 (SeaweedFS appends to shared .dat files, so a byte delta is not attributable to a single upload)
[UNKNOWN] disk-level removal not provable from volume stats; the S3 API guarantee (ListParts/ListMultipartUploads gone) is what is VERIFIED

=== POINT 7: CORS surface (browser part PUT / GET) ===
[INFO] OPTIONS preflight PUT -> HTTP 200 {'access-control-allow-headers': 'content-type, x-amz-server-side-encryption', 'access-control-allow-methods': 'GET, PUT, POST, DELETE, HEAD', 'access-control-allow-origin': 'https://compat.example.test', 'access-control-expose-headers': 'ETag, Content-Length, Content-Type, Last-Modified, x-amz-request-id, x-amz-version-id'}
[PASS] preflight allows the origin
[PASS] preflight allows PUT
[INFO] PUT with Origin -> HTTP 200 {'access-control-allow-headers': '*', 'access-control-allow-methods': 'GET, PUT, POST, DELETE, HEAD', 'access-control-allow-origin': 'https://compat.example.test', 'access-control-expose-headers': 'ETag, Content-Length, Content-Type, Last-Modified, x-amz-request-id, x-amz-version-id'}
[PASS] part PUT exposes ETag to the browser (Access-Control-Expose-Headers)
[INFO] part PUT ETag header present on the wire: '"3c484266f9315485694556e6c693bfa2"'
[INFO] GET with Origin -> HTTP 200 {'access-control-allow-headers': '*', ...same CORS headers...}

=== SUMMARY: failures=0 unknowns=1 ===
harness exit code: 0 (0 = every asserted point passed)
=== TEARDOWN ===
removed containers/network/workdir (/tmp/opencode/compat-4-48-1792496514-3377105)
confirmed: no compat-4-48-* containers remain
```

## 4. Verdict per point

| # | Point | Status | Evidence (short) |
|---|---|---|---|
| 1 | CreateMultipartUpload / UploadPart / ListParts / Complete / Abort | **VERIFIED** | All 5 ops succeed; part ETag `"<md5hex>"`; final ETag `"<md5hex>-2"`; ContentLength matches; SHA-256 round-trip matches; ListParts after abort → `NoSuchUpload` 404 |
| 2 | Minimum non-last part size | **VERIFIED** | Two 1 MiB parts accepted at UploadPart; **Complete rejected** with `EntityTooSmall` HTTP 400; no object created (`NoSuchKey`) |
| 3 | Presigned per-part URL consumed by a plain HTTP client | **VERIFIED** | `urllib` PUT to a presigned `upload_part` URL → 200 + ETag; Complete with the exact returned ETags succeeded; SHA-256 matches |
| 4 | `ServerSideEncryption=AES256` on multipart | **VERIFIED** | KEK active (single PUT HEAD=AES256); Create does not echo SSE; parts WITHOUT the SSE header succeed, WITH it (unsigned) → 403; HEAD after Complete = AES256; download SHA-256 matches |
| 5 | Byte-range GET | **VERIFIED** | `Accept-Ranges: bytes`; `bytes=0-99` → 206 `Content-Range: bytes 0-99/6291456`; `bytes=-50` → 206; out-of-range → 416 `InvalidRange`; multi-range not honored (see §6) |
| 6 | Abort / cleanup | **VERIFIED (API) / UNKNOWN (physical reclaim)** | Abort accepted; ListParts → `NoSuchUpload`; ListMultipartUploads empty. Volume bytes did not change after abort → physical reclaim cannot be proven |
| 7 | CORS surface for part PUT | **VERIFIED** | Preflight 200; `Access-Control-Allow-Origin` echoes the configured origin; `Access-Control-Allow-Methods` includes PUT; **`Access-Control-Expose-Headers` includes `ETag`** → browser can read the part ETag |

No point is FAILED or BLOCKED. Point 6's disk sub-question is UNKNOWN, explicitly.

## 5. Limits the future transfer client MUST encode

1. **Minimum part size = 5 MiB for every non-last part.** SeaweedFS accepts a
   smaller part at `UploadPart` and only fails at `CompleteMultipartUpload`
   (`EntityTooSmall`, HTTP 400). The client must therefore enforce the minimum
   *before* uploading, or be ready to abort and restart the upload on this error.
   The last part may be < 5 MiB (and may be 0 only if empty objects are allowed).
2. **ETag echo is mandatory.** `CompleteMultipartUpload` must send the
   **exact** per-part ETags returned by `UploadPart`/`ListParts`, including the
   surrounding double quotes. The client must capture the ETag from each part
   response (this is why CORS must expose `ETag`).
3. **Part ETag is an MD5 of the part, not SHA-256.** The composite object ETag is
   `"<md5hex>-<partcount>"`. **Never treat any ETag as a content SHA-256**
   (frozen constraint `docs/TRANSFER-ENGINE.md:99-103`). Integrity must be checked
   by downloading and hashing, or by a future S3 checksum algorithm if adopted.
4. **Presigned per-part URLs:** the presigned `upload_part` URL signs only the
   `host` header (query carries `uploadId`, `partNumber`, `X-Amz-Signature`, ...).
   The HTTP client may send only signed headers plus non-`x-amz-*` headers (e.g.
   `Content-Type`). **Adding any unsigned `x-amz-*` header breaks the signature**
   — notably `x-amz-server-side-encryption` on `UploadPart` → 403
   `SignatureDoesNotMatch`. A browser multipart client therefore must **not**
   re-send the SSE header per part.
5. **SSE-S3 is set once, on `CreateMultipartUpload`.** It is not echoed in the
   create response but is inherited by the completed object (`HEAD` =
   `x-amz-server-side-encryption: AES256`) and the bytes round-trip. Parts must be
   uploaded **without** the SSE header.
6. **Single-range GET works; multi-range does not.** `bytes=0-9,20-29` returns
   HTTP 200 with the **entire** object (no `multipart/byteranges`). Resumable
   download must issue single-range requests only and must not assume `206` for a
   multi-range header.
7. **CORS:** `-s3.allowedOrigins` must list the app origin; the gateway already
   exposes `ETag` (plus `Content-Length`, `Content-Type`, `Last-Modified`) to the
   browser, so the client can read the part ETag with no extra backend work.
8. **Abort removes upload metadata immediately** (API-verified) but **physical
   volume bytes were not observed to be reclaimed** on abort; partial data may
   linger until SeaweedFS compaction/GC. Do not rely on abort to free disk
   immediately; monitor volume usage.

## 6. Deviations from AWS S3 observed

- `CreateMultipartUpload` does **not** echo `ServerSideEncryption` in its response
  (AWS does). The object is still encrypted: verify via `HEAD` after completion.
- **Multi-range `GET` is not supported**: a comma-separated `Range` is ignored and
  the full object is returned with `200`, not `206 multipart/byteranges`.
- Aborted multipart data is **not immediately reclaimed** (append-only volume
  files); AWS frees the parts on abort.
- Minimum part size, per-part MD5 ETag, composite ETag shape (`md5-N`), presigned
  part signing and `x-amz-*` signing rules otherwise match AWS expectations.

## 7. Not tested (explicit UNKNOWN)

- **S3 trailing checksums** (`x-amz-checksum-crc32/crc32c/sha1/sha256` on
  `PutObject`/`UploadPart`/`CreateMultipartUpload`) were **not** exercised by this
  harness. Coverage of the *« checksums »* wording is therefore limited to the
  ETag-vs-SHA-256 distinction above. Treat checksum-algorithm support as UNKNOWN;
  the client must verify integrity itself (download + SHA-256), never via ETag.
- **Multipart `UploadPartCopy`** was not tested (upstream open issue #11855 was
  flagged during research); out of scope for #84.

## 8. Reproduce / cleanup

```bash
sg docker -c 'bash tests/multipart-compat-4.48.sh'
```

The harness tears down its containers, network and `/tmp/opencode` workdir in a
`trap`, and refuses to start if any `compat-4-48-*` name or network is left over
from a previous crash. It never touches the pilot stack or the pilot `.env`.
