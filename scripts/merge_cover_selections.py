#!/usr/bin/env python3
"""Merge an exported cover selection into the canonical review safely.

An export can select or clear books, but it cannot delete canonical entries,
overwrite applied books, or revive a candidate removed by a later refresh.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

APPLIED_STATES = {"applied", "already_applied"}


def reject_constant(value: str):
    raise ValueError(f"valeur JSON non autorisee: {value}")


def load_review(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict) or not isinstance(data.get("books"), list):
        raise ValueError(f"{path}: liste 'books' absente")
    for book in data["books"]:
        if not isinstance(book, dict):
            raise ValueError(f"{path}: entree de livre non objet")
        candidates = book.get("candidates", [])
        if candidates is not None and (
            not isinstance(candidates, list)
            or any(not isinstance(candidate, dict) for candidate in candidates)
        ):
            raise ValueError(f"{path}: candidat non objet")
    return data


def merge_selections(canonical: dict, selections: dict) -> dict:
    exported_at = selections.get("exported_at")
    if not isinstance(exported_at, (int, float)) or isinstance(exported_at, bool):
        raise ValueError("exported_at doit etre un horodatage numerique")
    # Compare the snapshot rendered into the page, not only the later export
    # click time. An old page must not overwrite choices made after it rendered.
    for field in ("generated_at", "selection_updated_at"):
        snapshot = selections.get(field)
        current = canonical.get(field)
        same_export = (field == "selection_updated_at"
                       and canonical.get("last_selection_export_at") == exported_at)
        if isinstance(current, (int, float)) and not isinstance(snapshot, (int, float)):
            if not same_export:
                raise ValueError(f"instantané {field} absent de l'export; regenerez la page")
            continue
        if (isinstance(snapshot, (int, float)) and isinstance(current, (int, float))
                and snapshot < current and not same_export):
            raise ValueError(f"page de revue plus ancienne que {field}; regenerez-la")
        if (field == "selection_updated_at" and isinstance(current, (int, float))
                and exported_at < current and not same_export):
            raise ValueError("export plus ancien que la derniere selection; regenerez la page")

    result = copy.deepcopy(canonical)
    by_id = {book.get("object_id"): book for book in result["books"]}
    for chosen in selections["books"]:
        target = by_id.get(chosen.get("object_id"))
        if not target or target.get("status") in APPLIED_STATES:
            continue
        status = chosen.get("status")
        if status == "selected":
            url = str(chosen.get("chosen_url") or "")
            candidates = target.get("candidates") or []
            index = next((i for i, candidate in enumerate(candidates)
                          if candidate.get("url") == url), None)
            if index is None:
                raise ValueError(
                    f"selection perimee pour {target.get('title') or target.get('object_id')}"
                )
            target["status"] = "selected"
            target["chosen_url"] = url
            target["chosen_candidate"] = index
            target.pop("error", None)
        elif status == "pending" and target.get("status") in {"selected", "error"}:
            target["status"] = "pending"
            target["chosen_url"] = None
            target["chosen_candidate"] = None
            target.pop("error", None)

    result["last_selection_export_at"] = exported_at
    result["selection_updated_at"] = int(time.time())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canonical", type=Path)
    parser.add_argument("selections", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        merged = merge_selections(load_review(args.canonical), load_review(args.selections))
        args.output.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Erreur: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
