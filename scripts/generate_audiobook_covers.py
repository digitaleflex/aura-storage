#!/usr/bin/env python3
"""Enrich published audiobooks with a locally extracted cover.

No external metadata or cover API is used here. For each published audio object
with no cover yet, this script tries in order:

1. every early artwork stream embedded in the audio file (ID3 APIC / MP4 cover),
   not only the first video stream;
2. an image object stored beside the audio in the same bucket (``cover.jpg``,
   ``folder.jpg``, an image with the same stem, ...).

The chosen image is resized with ffmpeg and stored as
``{object_key}.cover.jpg`` with the same SSE settings as the payload. The
catalogue column ``cover_key`` is then set so ``/covers/{oid}.jpg`` can redirect
to it. Files with no local artwork keep the typographic fallback.

Bounded and resumable: only objects with no cover_key and no previous probe are
considered, at most --limit per run. Dry-run by default; pass --apply to write.
Use --reprobe once after upgrading to retry objects marked by the older
first-stream-only script (the probe timestamp is refreshed, so the daily cron
does not retry them forever).
"""
from __future__ import annotations

import argparse

from api import cover_enrichment as ce


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--reprobe", action="store_true",
        help="also retry objects already probed by the old first-stream-only script",
    )
    args = parser.parse_args()

    rows = ce.published_without_cover(args.limit, include_probed=args.reprobe)
    if not rows:
        print("aucun livre audio sans couverture")
        return 0

    client = ce.s3_client()
    image_cache: dict[str, list[dict]] = {}
    made, skipped = 0, 0
    for row in rows:
        jpeg = None
        source = ""
        audio_url = ce.presigned_get(client, row["bucket"], row["object_key"], 300)
        jpeg = ce.extract_embedded(audio_url)
        if jpeg:
            source = "artwork intégré"
        else:
            images = image_cache.setdefault(row["bucket"], ce.image_objects(row["bucket"]))
            for candidate in ce.sibling_candidates(row, images):
                image_url = ce.presigned_get(
                    client, candidate["bucket"], candidate["object_key"], 300
                )
                jpeg = ce.resize_image(ce.fetch_url(image_url) or b"")
                if jpeg:
                    source = f"image sœur {candidate['object_key']}"
                    break
        if jpeg:
            key = ce.publish_cover(row, jpeg, client, args.apply)
            print(f"  couverture ({source}): {row['display_name']} -> {key}")
            made += 1
        else:
            ce.mark_miss(row, args.apply)
            skipped += 1
    print(
        f"couvertures: {made} traitees, {skipped} sans art local "
        f"({'APPLIQUE' if args.apply else 'DRY-RUN'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
