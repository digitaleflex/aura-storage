#!/usr/bin/env python3
"""Offline before/after relevance check for the public portal's local search.

Usage: .venv/bin/python scripts/measure-portal-search.py [--output FILE]

The golden set below is synthetic, public-domain wording and reserved public
facets only. It measures the tokenisation change introduced by issue #321:
"before" is the previous accent-folded AND/substring search, "after" uses the
shared local canonicalisation from ``api.portal_search``. No listener data,
query log or private catalogue metadata is used or sent anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import portal_search, public_ui  # noqa: E402

# id, display name, author, reserved public themes/categories.
CORPUS = [
    ("thriller-1", "La Nuit du Polar", "Awa Diallo", ["thriller"]),
    ("thriller-2", "Suspense au Bord de l'Eau", "Awa Diallo", ["suspense"]),
    ("thriller-3", "Le Crime de l'Orient", "Léa Faye", ["policier"]),
    ("romance-1", "Un Amour de Pluie", "Léa Faye", ["romance"]),
    ("romance-2", "Les Jours Romantiques", "Awa Diallo", ["sentimental"]),
    ("bio-1", "Mémoires d'un Jardinier", "Noé Diop", ["biographie"]),
    ("bio-2", "Autobiographie d'une Étoile", "Noé Diop", ["biographie"]),
    ("sf-1", "Un Monde Futuriste", "Awa Diallo", ["science-fiction"]),
    ("sf-2", "Les Machines Pensantes", "Léa Faye", ["intelligence artificielle"]),
    ("ia-1", "Apprentissage Automatique", "Noé Diop", ["intelligence artificielle"]),
    ("histoire-1", "Chronique du Siècle", "Noé Diop", ["histoire"]),
    ("poesie-1", "Poèmes du Soir", "Léa Faye", ["poesie"]),
    ("jeunesse-1", "L'Ado et la Lune", "Awa Diallo", ["jeunesse"]),
    ("humour-1", "Comédie au Village", "Léa Faye", ["humour"]),
    ("plain-1", "Nuit Blanche", "Léa Faye", []),
]

# Query -> identifiers a reader would reasonably expect to see.
GOLDEN = {
    "polar": {"thriller-1", "thriller-2", "thriller-3"},
    "suspense": {"thriller-1", "thriller-2", "thriller-3"},
    "romantique": {"romance-1", "romance-2"},
    "mémoires": {"bio-1", "bio-2"},
    "science fiction": {"sf-1"},
    "ia": {"sf-2", "ia-1"},
    "chronique": {"histoire-1"},
    "poème": {"poesie-1"},
    "ado": {"jeunesse-1"},
    "comédie": {"humour-1"},
    "Nuit": {"thriller-1", "plain-1"},
    "requête inconnue": set(),
}
K = 5


def _searchable(item, canonical: bool) -> str:
    oid, name, author, themes = item
    text = f"{name} {author} {' '.join(themes)}"
    return portal_search.canonicalize(text) if canonical else public_ui.fold(text)


def _rank(query: str, canonical: bool) -> list[str]:
    words = (
        portal_search.search_tokens(query) if canonical
        else public_ui.fold(query).split()
    )
    hits = []
    for item in CORPUS:
        searchable = _searchable(item, canonical)
        if words and all(word in searchable for word in words):
            hits.append(item[0])
    return hits[:K]


def _score(query: str, expected: set[str], canonical: bool) -> dict:
    ranked = _rank(query, canonical)
    found = expected & set(ranked)
    first = next((i for i, oid in enumerate(ranked, 1) if oid in expected), None)
    recall = len(found) / len(expected) if expected else 1.0
    return {
        "query": query,
        "ranked": ranked,
        "recall_at_5": round(recall, 3),
        "reciprocal_rank": round(1 / first, 3) if first else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    args = parser.parse_args()

    report = {
        "corpus_size": len(CORPUS),
        "queries": len(GOLDEN),
        "k": K,
        "before": [],
        "after": [],
    }
    for query, expected in GOLDEN.items():
        report["before"].append(_score(query, expected, canonical=False))
        report["after"].append(_score(query, expected, canonical=True))
    for side in ("before", "after"):
        rows = report[side]
        report[f"mean_{side}_recall_at_5"] = round(
            sum(row["recall_at_5"] for row in rows) / len(rows), 3
        )
        report[f"mean_{side}_reciprocal_rank"] = round(
            sum(row["reciprocal_rank"] for row in rows) / len(rows), 3
        )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)


if __name__ == "__main__":
    main()
