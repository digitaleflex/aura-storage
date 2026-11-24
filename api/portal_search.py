"""Interprétation locale d'une recherche en langage naturel pour le portail.

Pas d'appel à un service externe : on reconnaît un petit nombre d'intentions
(durée, auteur, titre similaire) et on les traduit en filtres que le portail sait
déjà appliquer. Le texte non reconnu reste une recherche par mots-clés.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchIntent:
    q: str = ""
    author: str = ""
    min_seconds: int | None = None
    max_seconds: int | None = None
    sort: str = ""
    explanation: str = ""

    @property
    def recognised(self) -> bool:
        return bool(self.explanation)


def fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(c) != "Mn"
    )


_DURATION_TOKEN = re.compile(
    r"(?P<max>moins de|sous|en moins de|max(?:imum)?|<|inférieur a)\s*"
    r"|(?P<min>plus de|au moins|min(?:imum)?|>)\s*",
    re.I,
)
_DURATION = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>h|heures?|min|minutes?)\b", re.I
)
_BETWEEN = re.compile(
    r"entre\s+(?P<a>\d+(?:[.,]\d+)?)\s*(?P<ua>h|heures?|min|minutes?)\s*et\s*"
    r"(?P<b>\d+(?:[.,]\d+)?)\s*(?P<ub>h|heures?|min|minutes?)", re.I,
)
_AUTHOR = re.compile(
    r"\b(?:par|auteur|ecrit par|écrivain)\s+([^,;!?.]+)", re.I
)
_LIKE = re.compile(r"\bcomme\s+([^,;!?.]+)", re.I)


def _seconds(value: str, unit: str) -> int:
    number = float(value.replace(",", "."))
    return int(number * 3600 if unit.lower().startswith(("h", "he")) else number * 60)


def parse_search(text: str) -> SearchIntent:
    """Translate a French natural-language query into portal filters."""
    raw = " ".join((text or "").split())[:240]
    if not raw:
        return SearchIntent()
    working = raw
    notes: list[str] = []
    min_seconds = max_seconds = None
    author = ""
    q = raw
    sort = ""

    between = _BETWEEN.search(working)
    if between:
        a = _seconds(between.group("a"), between.group("ua"))
        b = _seconds(between.group("b"), between.group("ub"))
        min_seconds, max_seconds = min(a, b), max(a, b)
        notes.append(f"durée entre {a // 60} et {b // 60} min")
        working = working.replace(between.group(0), " ")
    else:
        for match in list(_DURATION.finditer(working)):
            prefix = ""
            start = match.start()
            for prior in _DURATION_TOKEN.finditer(working[:start]):
                prefix = prior.group(0)
            seconds = _seconds(match.group("value"), match.group("unit"))
            if prefix and fold(prefix).startswith(("moins", "sous", "en moins", "max", "<", "infer")):
                max_seconds = seconds
                notes.append(f"moins de {seconds // 60} min")
            elif prefix and fold(prefix).startswith(("plus", "au moins", "min", ">")):
                min_seconds = seconds
                notes.append(f"plus de {seconds // 60} min")
            else:
                max_seconds = seconds
                notes.append(f"environ {seconds // 60} min")
            working = working.replace(match.group(0), " ", 1)

    like = _LIKE.search(working)
    if like:
        q = " ".join(like.group(1).split())[:120]
        notes.append(f"semblable à « {q} »")
        working = working.replace(like.group(0), " ")

    author_match = _AUTHOR.search(working)
    if author_match:
        author = " ".join(author_match.group(1).split())[:120]
        notes.append(f"auteur « {author} »")
        working = working.replace(author_match.group(0), " ")

    if any(word in fold(working) for word in ("recent", "nouveaute", "dernier")):
        sort = "recent"
        notes.append("nouveautés en premier")

    # Remove the already interpreted fragments from the free-text query.
    leftover = " ".join(working.split())
    if leftover and not like:
        q = leftover[:120]
    elif not q:
        q = leftover[:120]
    return SearchIntent(
        q=q, author=author, min_seconds=min_seconds, max_seconds=max_seconds,
        sort=sort, explanation=" · ".join(notes),
    )
