# AURA verification log — 2026-10-25 (SeaweedFS 4.48 multipart compatibility gate)

> Instance of [verification-log-template.md](verification-log-template.md). Contains no
> credentials, private keys, SSE-S3 keys, full environment dumps, customer filenames or
> document contents. The S3 credentials and the SSE-S3 KEK used here were generated for
> a throwaway stack and destroyed with it.

## Run metadata

- Date: 2026-10-25 (UTC). The harness run identifier embeds `1792965551`, i.e.
  21:59:11 UTC; the preserved output does not print a separate clock time. The
  gateway's own `Date` headers in the capture read `21:59:23 GMT`.
- Operator: `aura-admin` (AI-assisted session; this file is a documentation-only record).
- Repository: `aura-storage`, HEAD `3922cd4` at the time of writing. The captured output
  does not record the working-tree state at run time.
- Purpose: record the compatibility gate for issue #84 / [ENG-03] and the multipart plan
  ([MULTIPART-UPLOAD-PLAN.md](MULTIPART-UPLOAD-PLAN.md)) on the pinned 4.48 release.
- Artifact: `chrislusf/seaweedfs:4.48`, tag hard-coded by the harness (no `:latest`).
  The harness printed the resolved image:
  `sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`
  (`chrislusf/seaweedfs@sha256:4e61d15f…7872d`, created `2026-09-28T18:41:21Z`).
- Harness: `tests/multipart-compat-4.48.sh` + `tests/multipart_compat_client.py`.

## Exact command used

```bash
sg docker -c 'bash tests/multipart-compat-4.48.sh'
```

The harness starts the isolated stack itself, generates the throwaway S3 credentials,
the throwaway `WEED_S3_SSE_KEK` and the bucket name, runs the Python client against an
ephemeral `127.0.0.1` port, and removes everything in its `trap`. No secret is passed
on a command line or written to this log.

Capture note: the preserved output is the full harness stdout, from the image
line through `POINT 1`–`POINT 10` to the teardown and the final
`=== SUMMARY ===` line (130 lines). Nothing in the run's stdout is omitted here
except verbosity inside individual evidence lines, which are quoted verbatim
where they matter.

## Environment and isolation

- Image pinned: `chrislusf/seaweedfs:4.48`.
- Topology: master + volume + filer/S3 gateway, each its own container
  (`compat-4-48-master`, `compat-4-48-volume`, `compat-4-48-filer`) on its own Docker
  network (`compat-4-48-net`), data under `/tmp/opencode/compat-4-48-*`.
- Credentials: generated per run, throwaway `s3.json` (mode 0600), throwaway SSE-S3 KEK.
- Exposure: single ephemeral host port bound to `127.0.0.1`; plain HTTP only, no TLS.
- Pilot isolation: the harness never creates, inspects or touches the pilot stack
  (`aura-001-*` / compose project `aura-storage`), and never reads the pilot `.env`.
  It refuses to start if a `compat-4-48-*` container or network is left over.
- Teardown: `removed containers/network/workdir
  (/tmp/opencode/compat-4-48-1792965551-2472199)` followed by
  `confirmed: no compat-4-48-* containers remain`.

## Results

Summary as printed: `=== SUMMARY: failures=0 unknowns=1 passes=36 ===`, harness
exit code `0` (`0 = every asserted point passed`).

| # | Point exercised | Status | Evidence (from the captured output) |
|---|---|---|---|
| 1 | Core multipart lifecycle: create / part / list / complete / abort | **PASS** | `UploadId` present; two parts `"3c484266f9315485694556e6c693bfa2"` (5,242,880 B) and `"4c547f435fd36f510bdac9ee7971b023"` (1,048,576 B); `ListParts` reports both; complete ETag `"06f45652520586381550a3e2968b4eaf-2"`; HEAD `ContentLength=6291456` = sum of parts; GET SHA-256 matches; abort accepted; `ListParts` after abort → 404 `NoSuchUpload` |
| 2 | Minimum part size (non-last part < 5 MiB) | **PASS** | Two 1 MiB parts uploaded fine; `Complete` rejected → HTTP 400 `EntityTooSmall` ("Your proposed upload is smaller than the minimum allowed object size."); no object left at the key (`NoSuchKey`) |
| 3 | Presigned per-part PUT over plain HTTP (`urllib`, not boto3) | **PASS** | Two `urllib` PUTs to presigned `upload_part` URLs → HTTP 200 with the same part ETags; complete with the exact returned ETags → `"06f45652…-2"`; round-trip SHA-256 matches |
| 4 | SSE-S3 on multipart | **PASS** | Single PUT HEAD = `AES256`; unsigned SSE header on part 1 → 403 `SignatureDoesNotMatch`; parts without it → 200; HEAD after Complete = `AES256`; downloaded bytes match |
| 5 | Byte-range GET | **PASS** | Full GET 200 (6,291,456 bytes); `Range: bytes=0-99` → 206 with 100 bytes; `bytes=-50` → 206 last 50 bytes; out-of-range → 416 `InvalidRange`; multi-range is not honoured (200 + full body) |
| 6 | Abort cleanup | **PASS (S3 API) / UNKNOWN (disk)** | Abort accepted; `ListParts` → 404 `NoSuchUpload`; `ListMultipartUploads` → `[]`; volume byte counters unchanged — see the UNKNOWN below |
| 7 | CORS surface for part PUT / GET | **PASS** | `OPTIONS` preflight → 200 allowing the origin and PUT; part PUT with `Origin` → 200; `Access-Control-Expose-Headers` = `ETag, Content-Length, Content-Type, Last-Modified, x-amz-request-id, x-amz-version-id`; GET with `Origin` → 200 |
| 8 | Is the `UploadPart` ETag the MD5 of that part's bytes? | **PASS** | Yes, byte-for-byte, on all four probed shapes (5 MiB, 5 MiB + 4099 B, 3 B, 0 B); the assembled object's ETag is the composite MD5 — raw values below |
| 9 | `x-amz-checksum-sha256` on a presigned `UploadPart` | **PASS** | Signed header → 200 and echoed; unsigned → 403 `SignatureDoesNotMatch`; signed wrong digest → 400 `BadDigest`; the value is validated but not persisted — `ListParts`, Complete and `HeadObject(ChecksumMode=ENABLED)` expose no checksum — raw values below |
| 10 | Completed-object ETag and checksum surface | **PASS** | Complete = HEAD = `"2eca9979f6e33744ed05ea0285420b39-3"` = `md5(concat(part MD5s))-3`, `ContentLength=10497951`; HEAD exposes no `x-amz-checksum-*` and no `Checksum*` field; the whole-object SHA-256 is only obtainable by re-reading — raw values below |

No point was reported as FAILED or BLOCKED. The single UNKNOWN is the disk-level half
of point 6.

## Point 8 — the part ETag is the MD5 of the part (raw evidence)

The probe sizes were chosen to rule out a chunk-size coincidence: an exact 5 MiB part,
a part of 5 MiB + 4099 bytes (deliberately not aligned to any power-of-two chunk size),
a 3-byte last part, and a 0-byte part.

| Part | Bytes on the wire | MD5 computed locally | ETag returned | HTTP |
|---|---|---|---|---|
| 1 | 5,242,880 | `3c484266f9315485694556e6c693bfa2` | `"3c484266f9315485694556e6c693bfa2"` | 200 |
| 2 | 5,246,979 | `de22cbac3f980c82e8f87d5cdc95b96b` | `"de22cbac3f980c82e8f87d5cdc95b96b"` | 200 |
| 3 | 3 | `2a3e1ba1171a327b85a7a71d88043a6c` | `"2a3e1ba1171a327b85a7a71d88043a6c"` | 200 |
| — | 0 | `d41d8cd98f00b204e9800998ecf8427e` | `"d41d8cd98f00b204e9800998ecf8427e"` | 200 |

The 0-byte `UploadPart` was **accepted**, not rejected, and its ETag is the MD5 of the
empty string. For the three controlled parts, Complete and HEAD both reported the ETag
`"e3c484e5dc5d4efb706d2ee32a28b89f-3"` (HEAD with `ContentLength=10489862`) — exactly
the MD5 of the concatenated part digests plus `-3` — and the re-read bytes hashed to
`27900be8f24c1bbaa89d473826c8f66a01b7a8e2f88ef38a35d738b80bdeedc9`, equal to the
expected SHA-256 of the concatenation.

Every `UploadPart` response also carried a server-computed `x-amz-checksum-crc32`
(`rsHCFw==`, `SLmdtw==`, `MLissQ==`, `AAAAAA==` in the four cases above). That value
is not persisted: no later call returns it.

## Point 9 — `x-amz-checksum-sha256` on a presigned `UploadPart` (raw evidence)

| Case | What was sent | Result |
|---|---|---|
| 9a | checksum included in the presign (`X-Amz-SignedHeaders='host;x-amz-checksum-sha256'`), header `ONOx0yzcL06EY3/QF/5AvAnnlMEG/jleWG93YXH31O0=` | HTTP 200, ETag `"25d2d1999157e62fe9ff79ff9de06274"`, response echoes `x-amz-checksum-sha256: ONOx0yzc…1O0=` |
| 9b | same header, **not** in the presign (`X-Amz-SignedHeaders='host'`) | HTTP 403 `SignatureDoesNotMatch` |
| 9c | 8-byte body, signed **wrong** digest `CghiepJc15Tq7NIxW+6bJ7WHOEnSOEuXuzvjoCwg8tM=` | HTTP 400 `BadDigest`, message: "The Content-Md5 you specified did not match what we received." (it names MD5 although the algorithm was SHA-256) |
| 9d | `ListParts` after 9a | one part, ETag `"25d2d1999157e62fe9ff79ff9de06274"`, `Size 5242880`, `ChecksumSHA256` = `None` |
| 9e | part 2 signed with `KvBeeObpWyTkH8fQZr2NjUBrA3EUQXXbaMyJJu+AFZs=` | HTTP 200, ETag `"dab324baf62ee459d95830b718f0eef1"` |
| 9f | Complete of 9a + 9e | ETag `"7951efc98039eace1af58bc592633e7a-2"`, `checksum_fields={}`, response keys `['Bucket', 'ETag', 'Key', 'Location']` |
| 9g | `HeadObject(ChecksumMode=ENABLED)` | no `Checksum*` key and no `x-amz-checksum-*` header |

Two consequences. A checksum header on a presigned part PUT must be inside the
signature, exactly like the SSE header above; adding it afterwards is a 403. And the
gateway validates the value it is handed, then forgets it: nothing about the checksum
survives the part call.

## Point 10 — completed-object ETag and checksum surface (raw evidence)

| Part | Bytes | Part ETag (= MD5) |
|---|---|---|
| 1 | 5,242,880 | `"08b46181d7094b5ece88bb389c7499af"` |
| 2 | 5,251,071 | `"8e32e3db1e71ac49c2cf105fa769f6e3"` |
| 3 | 4,000 | `"f8b0e953f97321f139b0eb8b6d3e8c1d"` |

Complete → `"2eca9979f6e33744ed05ea0285420b39-3"`; HEAD → the same string;
`ContentLength=10497951`; the locally computed MD5 of the concatenated part digests,
plus `-3`, is that same string. The HEAD response carried no `x-amz-checksum-*` header
and no `Checksum*` field (`checksum_fields={}`). A whole-object SHA-256 cannot be
derived from a composite ETag, which is MD5-based; a re-read of the 10,497,951 bytes
hashed to `7d95d253ffdfe09c8f87b4cd0b9acb6559dd58f0d4471a5f8aad075da29bbe43`, matching
the expected SHA-256. That re-read is the only way this capture obtained a whole-object
digest from the S3 API.

## The single UNKNOWN (stated prominently)

**Disk-level removal after abort is NOT proven.** The probe compared volume `/data`
stats:

- before upload: `(4 files, 22,029,607 bytes)`
- after 2 × 5 MiB parts: `(4 files, 27,279,455 bytes)`
- after abort: `(4 files, 27,279,455 bytes)`

SeaweedFS appends to shared `.dat` files, so a byte delta cannot be attributed to one
upload. The harness therefore records:

> `[UNKNOWN] disk-level removal not provable from volume stats; the S3 API guarantee
> (ListParts/ListMultipartUploads gone) is what is VERIFIED`

The S3 API guarantee is verified. Physical reclamation is not, and this log does not
claim it.

## Operational note: never re-send the SSE header on `UploadPart`

This is the finding most likely to break a browser multipart client:

- `CreateMultipartUpload` accepts SSE-S3, but does not echo `ServerSideEncryption` in
  its response. That is expected and is not an error.
- A presigned `UploadPart` URL does not cover an added
  `x-amz-server-side-encryption` header. Adding it **unsigned** makes the request fail
  with HTTP 403 `SignatureDoesNotMatch`.
- The same part uploads successfully (HTTP 200) when the SSE header is omitted.
- The completed object is still encrypted: `HEAD` after Complete reports
  `x-amz-server-side-encryption: AES256`, and the downloaded bytes match the uploaded
  SHA-256.

Client rule: request SSE-S3 **once at `CreateMultipartUpload`**, never per part, and
do not add `x-amz-*` headers to a presigned part PUT.

## Operational note: per-part integrity is verifiable from `ListParts` alone

Point 8 establishes that a part's ETag is exactly the MD5 of that part's bytes — at
5 MiB, at a non-aligned 5 MiB + 4099 bytes, at 3 bytes, and at 0 bytes. With point 10
(the completed ETag is `md5(concat(part MD5 bytes))-N`) this yields three facts that
matter operationally:

- Each part's digest can be checked against `ListParts` with **no object read**.
- A client that hashed the part it sent holds a value the server can confirm
  authoritatively: the reference is the `ListParts` ETag, not a client claim.
- The assembled-object ETag is a chain of those per-part MD5 digests. It says nothing
  about SHA-256, and no whole-object SHA-256 is recoverable from it.

So server-side per-part integrity verification does not require reading the object.
This is the evidentiary basis of the proposal in
[DECISION-PART-CHECKSUMS.md](DECISION-PART-CHECKSUMS.md), which would let the server
skip its own SHA-256 read — noting that for objects ≥ 32 MiB that read already runs in
the verification worker rather than inside the commit request. That decision was
reviewed on 2026-10-25 and **deferred**; nothing is implemented.

## What this does NOT prove

- **Real browser behaviour.** No browser was used anywhere in this run: the presigned
  URLs were consumed with Python `boto3`/`urllib`, and point 7's CORS "PASS" is
  header inspection on the wire, not browser enforcement. No preflight cache, no
  browser CORS enforcement, no `fetch`/XHR limits, and no execution of
  `web/src/lib/transfer.ts` were exercised.
- **The AURA API or web path.** The harness talks directly to the S3 gateway with
  throwaway credentials. It does not prove the AURA API's presigning, session state,
  commit verification, abort/reconcile, or the UI.
- **The pilot stack or the edge proxy.** The endpoint was loopback
  (`http://127.0.0.1:<ephemeral>`); Traefik was not in the path. This run does **not**
  cover plan gate item 6: part PUTs through the edge proxy, nor the largest part that
  fits the configured `readTimeout` at the slowest supported client rate.
- **Browser readability of the checksum echo header.** Point 9 saw
  `x-amz-checksum-sha256` echoed on the part PUT response, but
  `Access-Control-Expose-Headers` lists only `ETag, Content-Length, Content-Type,
  Last-Modified, x-amz-request-id, x-amz-version-id`. In a real browser the echoed
  checksum is therefore **not** readable from JavaScript, while the part ETag is.
  That gap was not exercised in a browser (none was used here). The gateway-side
  checksum questions (accept, validate, persist) are answered above; the browser
  question is not.
- **Maximum part count and large objects.** The visible object is 6 MiB (5 MiB + 1 MiB
  parts). The maximum part count, multi-gigabyte objects, part-size defaults and
  concurrency were not measured.
- **Throughput.** No bandwidth, latency or proxy-timeout measurement was made.
- **Disk reclamation / compaction / GC.** The UNKNOWN above stands; abort is not shown
  to free disk immediately.
- **Crash recovery and persistence.** No container kill, restart, host reboot or
  crash-during-complete scenario was tested.
- **TLS and real authentication.** Plain HTTP over loopback with throwaway
  credentials; certificate validation and pilot credential handling are out of scope.
- **A clean gate PASS.** Plan gate item 6 (part PUTs through the edge proxy plus
  `readTimeout` sizing) is still uncovered, and point 6 contains the UNKNOWN above.
  `AURA_MULTIPART_ENABLED` therefore stays at its default `off`; this run alone does
  not authorise enabling it.

## Decision

- Gate executed and recorded on 2026-10-25 against `chrislusf/seaweedfs:4.48`:
  36 passes, 0 failed assertions, 1 UNKNOWN.
- **Not a clean "all points PASS"**: the abort/disk-reclaim sub-question is UNKNOWN,
  and plan gate item 6 (edge proxy / `readTimeout` sizing) is not covered by this
  run. Gate item 3 (checksums) *is* covered by this run — see points 8–10.
- `AURA_MULTIPART_ENABLED` must remain `0` (default off). Do not enable on this
  evidence alone.
- Next evidence needed: Traefik-path part PUT with `readTimeout` sizing, browser-side
  readability of the checksum echo header, maximum part count, and—if disk
  reclamation matters operationally—volume compaction/GC observation after abort.

## References

- [S3 multipart upload plan](MULTIPART-UPLOAD-PLAN.md)
- [Earlier 2026-10-20 engineering record](engineering/multipart-compat-4.48.md)
  (separate run, separate capture; this 2026-10-25 record is the authoritative one for
  the points it covers, including POINT 1/POINT 2)
- [Decision: part checksums](DECISION-PART-CHECKSUMS.md) — **deferred** on review,
  not implemented; rests on points 8–10 above
- Harness: `tests/multipart-compat-4.48.sh`, `tests/multipart_compat_client.py`
