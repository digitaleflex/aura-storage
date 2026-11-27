"""Editorial classification for the public audiobook catalogue.

The catalogue stores public facets as reserved object tags.  This module keeps
the taxonomy and the deterministic proposal logic in one place so the one-off
backfill and future publications use the same rules.  A proposal never replaces
an existing editorial classification unless the caller explicitly asks for it.
"""
from __future__ import annotations

import re
import unicodedata

CATEGORY_LABELS = {
    "developpement": "Développement personnel",
    "finance": "Finance & entrepreneuriat",
    "leadership": "Leadership & productivité",
    "psychologie": "Psychologie & relations",
    "spiritualite": "Spiritualité & bien-être",
    "cybersecurite": "Cybersécurité & technologie",
    "litterature": "Littérature & philosophie",
    "meditation": "Méditation & audio guidé",
}

CATEGORY_ICONS = {
    "developpement": "sprout",
    "finance": "chart",
    "leadership": "compass",
    "psychologie": "heart",
    "spiritualite": "sun",
    "cybersecurite": "shield",
    "litterature": "book",
    "meditation": "lotus",
}

THEME_LABELS = {
    "argent": "Argent",
    "bien-etre": "Bien-être",
    "communication": "Communication",
    "confiance-en-soi": "Confiance en soi",
    "criminalite": "Criminalité",
    "culture-generale": "Culture générale",
    "cybersecurite": "Cybersécurité",
    "emotions": "Émotions",
    "entrepreneuriat": "Entrepreneuriat",
    "histoire": "Histoire",
    "influence": "Influence",
    "intelligence-artificielle": "Intelligence artificielle",
    "leadership": "Leadership",
    "meditation": "Méditation",
    "memoire": "Mémoire",
    "motivation": "Motivation",
    "philosophie": "Philosophie",
    "productivite": "Productivité",
    "psychologie": "Psychologie",
    "relations": "Relations",
    "spiritualite": "Spiritualité",
    "strategie": "Stratégie",
    "stress": "Stress",
}

# Folder names are only a proposal source.  They remain private and are never
# exposed as public labels.
FOLDER_CATEGORIES = {
    "audiobook - meditations guidees respirez - @ebooks_fr": "meditation",
    "podcast cyber substack": "cybersecurite",
    "brian tracy": "leadership",
    "brian tracy - capsules": "leadership",
    "robert greene": "leadership",
    "stephen covey": "leadership",
    "john c. maxwell": "leadership",
    "jake knapp": "leadership",
    "tim ferriss": "leadership",
    "francois aelion": "leadership",
    "jean riviere": "leadership",
    "nicholas boothman": "leadership",
    "robert kiyosaki": "finance",
    "david demaire": "finance",
    "dale carnegie": "psychologie",
    "gary chapman": "psychologie",
    "don miguel ruiz": "psychologie",
    "joan garriga": "psychologie",
    "lise bourbeau": "psychologie",
    "james lee king": "psychologie",
    "yvan castanou": "psychologie",
    "s'aimer, c'est donner un sens": "psychologie",
    "matthieu ricard": "meditation",
    "doreen virtue": "spiritualite",
    "florence scovel shinn": "spiritualite",
    "neale donald walsch": "spiritualite",
    "patrick burensteinas": "spiritualite",
    "paulo coelho": "spiritualite",
    "peter deunov": "spiritualite",
    "rhonda byrne": "spiritualite",
    "robert lissen": "spiritualite",
    "sonia choquette": "spiritualite",
    "wayne dyer": "spiritualite",
    "joe vitale": "spiritualite",
    "joe dispenza": "spiritualite",
    "kevin trudeau": "spiritualite",
    "louise hay": "spiritualite",
    "joseph murphy": "spiritualite",
    "john kehoe": "spiritualite",
    "jiddu krishnamurti": "spiritualite",
    "maxwell maltz": "developpement",
    "dan millman": "spiritualite",
    "dante alighieri": "litterature",
    "yuval noah harari": "litterature",
}

TITLE_CATEGORY_OVERRIDES = {
    "entrepreneuriat": "finance",
    "chevre de ma mere": "litterature",
    "plus grand vendeur": "leadership",
}

CATEGORY_RULES = (
    ("cybersecurite", ("cybercriminal", "cybersecur", "cybercrime", "cyberguerre", "piratage", "rancongiciel", "passkeys")),
    ("meditation", ("meditation", "meditez", "respirez", "audio guide")),
    ("finance", ("finance", "financier", "argent", "riche", "richesse", "cashflow", "millionnaire", "entrepreneuriat")),
    ("psychologie", ("emotion", "stress", "conflit", "amour", "mariage", "blessure", "manipuler", "psychologie", "confiance")),
    ("spiritualite", ("spiritu", "eveil", "dieu", "karma", "secret", "intention", "vibration", "lumiere", "subconscient", "foi")),
    ("litterature", ("philosoph", "spinoza", "tao te king", "culture generale", "divine comedie", "xxe siecle", "histoire")),
    ("leadership", ("leadership", "strategie", "guerre", "pouvoir", "persuasion", "convaincre", "charisme", "seduction", "productivite", "objectif", "succes", "reussite", "excellence", "projet", "vente")),
)

THEME_RULES = (
    ("intelligence-artificielle", ("intelligence artificielle", "cybercriminal", "cybersecur", "cybercrime", "cyberguerre", "ia_", "_ia", "numerique", "post-quantique")),
    ("cybersecurite", ("cybercriminal", "cybersecur", "cybercrime", "cyberguerre", "piratage", "rancongiciel", "passkeys", "identite", "securite")),
    ("strategie", ("strategie", "guerre", "lois du pouvoir", "ocean bleu")),
    ("influence", ("persuasion", "convaincre", "charisme", "seduction", "influencer", "manipuler", "plus grand vendeur")),
    ("productivite", ("productivite", "gestion du temps", "objectif", "sprint", "projet", "temps")),
    ("memoire", ("memoire",)),
    ("motivation", ("motivation", "succes", "reussite", "reussir", "limites", "determination", "rage de reussir", "potentiel")),
    ("stress", ("stress", "stressant")),
    ("emotions", ("emotion", "emotions", "negatives")),
    ("psychologie", ("psychologie", "psycho", "blessure", "auto-sabotage")),
    ("relations", ("amour", "mariage", "relation", "conflit")),
    ("confiance-en-soi", ("confiance", "estime", "subconscient", "auto-hypnose", "croyez en vous")),
    ("spiritualite", ("spiritu", "eveil", "dieu", "karma", "secret", "intention", "vibration", "lumiere", "foi", "guerrier de la lumiere")),
    ("philosophie", ("philosoph", "spinoza", "tao te king", "lois de l'esprit", "sens du bonheur")),
    ("argent", ("finance", "financier", "argent", "riche", "richesse", "cashflow", "millionnaire", "prosperite")),
    ("histoire", ("histoire", "divine comedie", "xxe siecle")),
    ("culture-generale", ("culture generale",)),
    ("meditation", ("meditation", "meditez", "respirez")),
)

DEFAULT_THEMES = {
    "developpement": ("motivation", "bien-etre"),
    "finance": ("argent", "entrepreneuriat"),
    "leadership": ("leadership", "productivite"),
    "psychologie": ("psychologie", "relations"),
    "spiritualite": ("spiritualite", "bien-etre"),
    "cybersecurite": ("cybersecurite", "intelligence-artificielle"),
    "litterature": ("philosophie", "culture-generale"),
    "meditation": ("meditation", "bien-etre"),
}

PUBLIC_PREFIXES = ("categorie-", "theme-", "langue-")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.lower().replace("_", " ").split())


def classify_public_item(display_name: str, folder_name: str = "") -> dict:
    """Return one primary category, up to three themes and the main language."""
    folder = _fold(folder_name)
    title = _fold(display_name)
    text = f"{folder} {title}"
    category = next(
        (slug for phrase, slug in TITLE_CATEGORY_OVERRIDES.items() if phrase in title),
        None,
    ) or FOLDER_CATEGORIES.get(folder)
    if not category:
        for candidate, needles in CATEGORY_RULES:
            if any(needle in text for needle in needles):
                category = candidate
                break
    category = category or "developpement"

    themes: list[str] = []
    for theme, needles in THEME_RULES:
        if any(needle in text for needle in needles):
            themes.append(theme)
        if len(themes) == 3:
            break
    if not themes:
        themes.extend(DEFAULT_THEMES[category][:2])
    return {"category": category, "themes": themes[:3], "language": "fr"}


def classification_tags(classification: dict) -> list[str]:
    tags = [f"categorie-{classification['category']}"]
    tags.extend(f"theme-{theme}" for theme in classification.get("themes", []))
    tags.append(f"langue-{classification.get('language') or 'fr'}")
    return tags


def merge_public_tags(
    existing: list[str] | tuple[str, ...] | None,
    classification: dict,
    *,
    replace: bool = False,
) -> list[str]:
    """Merge a proposal with private tags, preserving manual public facets.

    ``replace=True`` is for the initial editorial backfill.  The publication
    path uses the default: an existing category/theme/language always wins.
    """
    current: list[str] = []
    for raw in existing or []:
        tag = str(raw).strip().lower()
        if TAG_RE.fullmatch(tag) and tag not in current:
            current.append(tag)
    if replace:
        current = [tag for tag in current if not tag.startswith(PUBLIC_PREFIXES)]
    else:
        if any(tag.startswith("categorie-") for tag in current):
            classification = {**classification, "category": None}
        if any(tag.startswith("theme-") for tag in current):
            classification = {**classification, "themes": []}
        if any(tag.startswith("langue-") for tag in current):
            classification = {**classification, "language": None}

    proposed = classification_tags(classification)
    if classification.get("category") is None:
        proposed = [tag for tag in proposed if not tag.startswith("categorie-")]
    if not classification.get("themes"):
        proposed = [tag for tag in proposed if not tag.startswith("theme-")]
    if classification.get("language") is None:
        proposed = [tag for tag in proposed if not tag.startswith("langue-")]
    for tag in proposed:
        if TAG_RE.fullmatch(tag) and tag not in current:
            current.append(tag)
    return current[:20]
