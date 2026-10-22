#!/usr/bin/env node
// Ask the AURA API for a short-lived URL to a file (Node >= 18, no dependency).
//
//   export AURA_API=https://app.example.org   # the app host, not the S3 host
//   export AURA_TOKEN=aura_...                 # service-identity token (objects:read)
//   node get-file-url.mjs <object-id> [download|preview]
//
// Run it from a server: the S3 gateway only allows CORS from the app origin, so a
// third-party web page cannot fetch() the URL (a plain <video src> or <img src>
// pointing at it does work, it needs no CORS).

const api = (process.env.AURA_API ?? "").replace(/\/$/, "");
const token = process.env.AURA_TOKEN;
const [id, kind = "download"] = process.argv.slice(2);
if (!api || !token || !id) {
  console.error("usage: AURA_API=... AURA_TOKEN=... node get-file-url.mjs <object-id> [download|preview]");
  process.exit(2);
}

const response = await fetch(`${api}/api/v1/objects/${encodeURIComponent(id)}/${kind}-intent`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
});
if (!response.ok) {
  const hints = { 401: "token missing, wrong or expired", 403: "missing objects:read scope",
    404: "no such object in this space", 409: "not 'available' yet", 415: "no inline preview for this type",
    429: `too many failed authentications; retry after ${response.headers.get("retry-after")} s` };
  console.error(`HTTP ${response.status} ${hints[response.status] ?? ""}`);
  process.exit(1);
}
const intent = await response.json();
console.log(`${intent.display_name}  ${intent.content_type}  ${intent.size_bytes} bytes`);
const ranges = "range_supported" in intent ? ` (range_supported=${intent.range_supported})` : "";
console.log(`expires in ${intent.expires_in} s${ranges}`);
console.log(intent.download_url ?? intent.preview_url);
