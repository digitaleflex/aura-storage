#!/usr/bin/env python3
"""Build the AURA high-fidelity design prototype.

Six mockups + a design-system page + an index, all generated from one data set
and one component library so the screens stay consistent.

Run:  python3 build.py
"""
from pathlib import Path

ROOT = Path(__file__).parent
COVER = "assets/covers/{}.svg"


# ---------------------------------------------------------------------------
# Illustrative catalogue (mock data — not the production library)
# ---------------------------------------------------------------------------
def book(slug, title, author, duration, cat, availability="Disponible",
         kind="available", narrator="Camille Delcourt", collection="Les classiques",
         progress=0, year=2026, summary=""):
    return dict(slug=slug, title=title, author=author, duration=duration,
                cat=cat, availability=availability, kind=kind, narrator=narrator,
                collection=collection, progress=progress, year=year, summary=summary)


BOOKS = [
    book("la-peste", "La Peste", "Albert Camus", "8 h 42", "Romans", narrator="Camille Delcourt",
         summary="Quand la peste s'installe à Oran, chacun compose avec l'absence et la solidarité. Une lecture intacte de l'œuvre majeure de Camus, portée par une voix sobre et lumineuse."),
    book("petit-prince", "Le Petit Prince", "Antoine de Saint-Exupéry", "1 h 34", "Jeunesse",
         availability="Extrait gratuit", kind="free", narrator="Élise Marchand", collection="À voix haute",
         summary="Un voyage minuscule et infini, à écouter le soir, à voix haute, avec ceux qui aiment encore les histoires."),
    book("madame-bovary", "Madame Bovary", "Gustave Flaubert", "10 h 18", "Romans",
         narrator="Claire Aubertin", progress=42,
         summary="Emma Bovary poursuit ailleurs l'image qu'elle se fait du bonheur. Flaubert observé au plus près, dans une lecture qui laisse respirer chaque phrase."),
    book("fleurs-du-mal", "Les Fleurs du mal", "Charles Baudelaire", "3 h 12", "Poésie",
         availability="Extrait gratuit", kind="free", narrator="Julien Ravel", collection="Voix de la poésie",
         summary="Les tableaux parisiens, les fleurs du mal et l'appel au voyage : la poésie de Baudelaire habitée par une voix qui sait écouter le silence entre deux vers."),
    book("etranger", "L'Étranger", "Albert Camus", "4 h 26", "Romans", narrator="Camille Delcourt", progress=18,
         summary="Meursault, indifférent au monde et fidèle à ses sens, raconte le jour où tout bascule. Une écoute tendue, presque chuchotée."),
    book("temps-retrouve", "Le Temps retrouvé", "Marcel Proust", "14 h 50", "Romans",
         availability="Premium", kind="premium", narrator="Hélène Vasseur", collection="La Recherche",
         summary="Le dernier volet de la Recherche : le temps retrouvé, l'art retrouvé. Une écoute longue, pour les après-midi sans fin."),
    book("monte-cristo", "Le Comte de Monte-Cristo", "Alexandre Dumas", "24 h 12", "Romans",
         narrator="Mathieu Sorel", collection="Grands récits",
         summary="Une évasion, un trésor, une vengeance lentement ourdie. Le grand roman de Dumas, en une traversée qu'on reprend volontiers."),
    book("miserables", "Les Misérables", "Victor Hugo", "28 h 30", "Romans",
         narrator="Mathieu Sorel", collection="Grands récits",
         summary="Jean Valjean, Javert, Cosette : l'immense fresque de Hugo racontée dans toute sa tendresse et sa colère."),
    book("de-lamour", "De l'Amour", "Stendhal", "5 h 40", "Essais", narrator="Claire Aubertin",
         summary="Stendhal dissèque le sentiment amoureux avec une précision désabusée. Un essai à écouter comme on relit une lettre ancienne."),
    book("journal-fou", "Le Journal d'un fou", "Guy de Maupassant", "1 h 12", "Nouvelles",
         availability="Extrait gratuit", kind="free", narrator="Julien Ravel", collection="Nouvelles",
         summary="Une nuit de veille, une raison qui se dérobe. Maupassant à son plus intime, en moins d'une heure."),
    book("contes", "Contes & Légendes", "Collectif", "3 h 55", "Jeunesse", narrator="Élise Marchand",
         collection="À voix haute", summary="Des récits anciens ramassés çà et là, à écouter en famille ou à garder pour soi."),
    book("nature-voyage", "La Nature en voyage", "Collectif", "4 h 20", "Documentaires",
         narrator="Hélène Vasseur", collection="Carnets", summary="Une traversée des paysages et des saisons, entre carnet de route et méditation."),
    book("poemes", "Poèmes choisis", "Emily Dickinson", "2 h 48", "Poésie", narrator="Claire Aubertin",
         collection="Voix de la poésie", progress=31,
         summary="Des centaines de petits éclats, lus à voix basse, à raison de quelques-uns par soirée."),
    book("sous-soleil", "Sous le soleil de Satan", "Georges Bernanos", "6 h 05", "Romans",
         narrator="Julien Ravel", summary="Un curé, un doute, une nuit. Bernanos et son style âpre, portés par une lecture à la limite du souffle."),
    book("nouvelles", "Nouvelles choisies", "Collectif", "3 h 36", "Nouvelles", narrator="Camille Delcourt",
         summary="Douze récits courts pour les trajets courts, choisis pour la justesse de leur chute."),
    book("lettres", "Lettres à un jeune poète", "R. M. Rilke", "2 h 24", "Essais", narrator="Hélène Vasseur",
         summary="Rilke répond à un jeune poète : patience, solitude, fidélité. Une écoute à replacer au centre de la journée."),
]

BY_SLUG = {b["slug"]: b for b in BOOKS}

FEATURED = BY_SLUG["la-peste"]
RESUME = [BY_SLUG["madame-bovary"], BY_SLUG["etranger"], BY_SLUG["poemes"]]
DISCOVER = [BY_SLUG[s] for s in ("petit-prince", "fleurs-du-mal", "sous-soleil", "poemes")]
NEW = [BY_SLUG[s] for s in ("contes", "lettres", "nature-voyage", "nouvelles")]
ALL = BOOKS[:12]
RELATED = [BY_SLUG[s] for s in ("etranger", "sous-soleil", "nouvelles")]


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------
P = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "book": '<path d="M4 5.5h6a2 2 0 0 1 2 2V20H6a2 2 0 0 1-2-2V5.5Z"/><path d="M20 5.5h-6a2 2 0 0 0-2 2V20h6a2 2 0 0 0 2-2V5.5Z"/><path d="M7 10h2M15 10h2"/>',
    "heart": '<path d="M12 20.5S4.5 16 4.5 10.3A3.9 3.9 0 0 1 12 8.1a3.9 3.9 0 0 1 7.5 2.2C19.5 16 12 20.5 12 20.5Z"/>',
    "play": '<path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke="none"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="2.4"/>',
    "pause-solid": '<rect x="7" y="5" width="3.4" height="14" rx="1" fill="currentColor"/><rect x="13.6" y="5" width="3.4" height="14" rx="1" fill="currentColor"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "headphones": '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="2.5" y="14" width="4.5" height="7" rx="2.2"/><rect x="17" y="14" width="4.5" height="7" rx="2.2"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/>',
    "home": '<path d="m3 11 9-7 9 7"/><path d="M5.5 10v10h13V10"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7"/><rect x="13.5" y="3.5" width="7" height="7"/><rect x="3.5" y="13.5" width="7" height="7"/><rect x="13.5" y="13.5" width="7" height="7"/>',
    "arrow": '<path d="M4 12h15m-6-6 6 6-6 6"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "share": '<circle cx="18" cy="5" r="2.6"/><circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="19" r="2.6"/><path d="m8.4 10.7 7.2-4.3M8.4 13.3l7.2 4.3"/>',
    "check": '<path d="m5 12 4.5 4.5L19 6.5"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2 6"/><path d="M20 5v6h-6"/>',
    "sparkle": '<path d="m12 3 1.7 5.4L19 10l-5.3 1.6L12 17l-1.7-5.4L5 10l5.3-1.6L12 3Z"/>',
    "bookmark": '<path d="M6.5 4h11v17l-5.5-3.8L6.5 21V4Z"/>',
    "queue": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "sleep": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
    "volume": '<path d="M4.5 9v6h4L14 19V5L8.5 9h-4Z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
    "expand": '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
    "download": '<path d="M12 3v12m0 0 4-4m-4 4-4-4M4 20h16"/>',
    "chevron": '<path d="m9 5 7 7-7 7"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "back": '<path d="m11 7-5 5 5 5"/><path d="M6 12h8a5 5 0 1 1 0 10"/>',
    "fwd": '<path d="m13 7 5 5-5 5"/><path d="M18 12h-8a5 5 0 1 0 0 10"/>',
    "prev": '<path d="M6 5v14M19 5 9 12l10 7V5Z"/>',
    "next": '<path d="M18 5v14M5 5l10 7L5 19V5Z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "book-open": '<path d="M12 6c-2-1.6-4.6-2-8-2v15c3.4 0 6 .4 8 2 2-1.6 4.6-2 8-2V4c-3.4 0-6 .4-8 2Z"/><path d="M12 6v15"/>',
}


def ic(name, cls="ic"):
    return (f'<svg class="{cls}" aria-hidden="true" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round">{P[name]}</svg>')


def cover_url(slug):
    return COVER.format(slug)


# ---------------------------------------------------------------------------
# Shared chrome
# ---------------------------------------------------------------------------
BRAND_SVG = (
    '<svg class="brand-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true">'
    '<rect x="1" y="1" width="38" height="38" rx="9" stroke="currentColor" stroke-width="1.3" opacity=".45"/>'
    '<path d="M11 12.5h6.2c1.5 0 2.8 1.2 2.8 2.8V29H12a1 1 0 0 1-1-1V12.5Z" stroke="currentColor" stroke-width="1.5"/>'
    '<path d="M29 12.5h-6.2c-1.5 0-2.8 1.2-2.8 2.8V29H28a1 1 0 0 0 1-1V12.5Z" stroke="currentColor" stroke-width="1.5"/>'
    '<path d="M14 18h2.5M23.5 18H26M14 22h2.5M23.5 22H26" stroke="currentColor" stroke-width="1.2"/>'
    '</svg>'
)


def brand(inverse=False):
    return f'<a class="brand" href="index.html" aria-label="AURA, accueil">{BRAND_SVG}<span class="brand-word">AURA</span></a>'


def head(active="", inverse=False):
    links = [
        ("01-accueil-desktop.html", "Accueil", "home"),
        ("03-bibliotheque.html", "Bibliothèque", "book"),
        ("01-accueil-desktop.html", "Découvrir", "compass"),
        ("05-lecteur.html", "En cours", "headphones"),
    ]
    nav = "".join(
        f'<a href="{href}"{cur}>{label}</a>'
        for href, label, cur in (
            (h, l, ' aria-current="page"' if active == l else '') for h, l, _ in links
        )
    )
    menu = f'<button class="icon-btn head-menu-toggle" aria-label="Ouvrir le menu">{ic("menu")}</button>'
    return f'''<header class="site-head">
  <div class="wrap head-inner">
    {brand(inverse)}
    <nav class="head-nav" aria-label="Navigation principale">{nav}</nav>
    <div class="head-end">
      <button class="icon-btn" aria-label="Rechercher">{ic("search")}</button>
      <button class="icon-btn" aria-label="Mes favoris">{ic("heart")}</button>
      <span class="avatar" aria-hidden="true">CL</span>
      {menu}
    </div>
  </div>
</header>'''


def mobile_head():
    return f'''<header class="site-head">
  <div class="wrap head-inner">
    {brand()}
    <div class="head-end">
      <button class="icon-btn" aria-label="Rechercher">{ic("search")}</button>
      <button class="icon-btn" aria-label="Ouvrir le menu">{ic("menu")}</button>
    </div>
  </div>
</header>'''


def mobile_nav(active="Accueil"):
    items = [
        ("Accueil", "home", "02-accueil-mobile.html"),
        ("Découvrir", "compass", "01-accueil-desktop.html"),
        ("Bibliothèque", "book", "03-bibliotheque.html"),
        ("En cours", "headphones", "05-lecteur.html"),
        ("Profil", "user", "design-system.html"),
    ]
    links = "".join(
        f'<a href="{href}"{cur}>{ic(icon)}<span>{label}</span></a>'
        for label, icon, href, cur in (
            (l, i, h, ' aria-current="page"' if l == active else '') for l, i, h in items
        )
    )
    return f'<nav class="mobile-nav" aria-label="Navigation mobile">{links}</nav>'


def foot():
    return '''<footer class="site-foot">
  <div class="wrap foot-grid">
    <div class="foot-brand"><div class="brand">''' + BRAND_SVG + '''<span class="brand-word">AURA</span></div>
      <p>Une bibliothèque à écouter.</p></div>
    <nav class="foot-links" aria-label="Liens de pied de page">
      <a href="01-accueil-desktop.html">À propos</a><a href="03-bibliotheque.html">La collection</a>
      <a href="design-system.html">Accessibilité</a><a href="design-system.html">Confidentialité</a>
      <a href="index.html">Contact</a>
    </nav>
    <p class="foot-legal">AURA — prototype de design. Titres, voix, durées et couvertures sont des données illustratives.</p>
  </div>
</footer>'''


def mini_player():
    return '''<div class="mini-player" hidden aria-label="Lecteur audio">
  <div class="mini-seek"><i style="width:24%"></i></div>
  <div class="wrap mini-inner">
    <div class="mini-cover"><img data-mini-cover src="assets/covers/la-peste.svg" alt=""></div>
    <div class="mini-copy"><strong data-mini-title>La Peste</strong><span data-mini-author>Albert Camus</span></div>
    <div class="mini-controls">
      <button class="t-btn small" aria-label="Reculer de 15 secondes"><span class="ic">−15</span></button>
      <button class="t-btn main js-mini-play" aria-label="Mettre en pause">''' + ic("pause-solid", "ic") + '''</button>
      <button class="t-btn small" aria-label="Avancer de 15 secondes"><span class="ic">+15</span></button>
      <a class="t-btn small" href="05-lecteur.html" aria-label="Ouvrir le lecteur">''' + ic("expand") + '''</a>
    </div>
  </div>
</div>'''


def doc(title, body, page_class=""):
    return f'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="AURA — maquette de design, bibliothèque audio éditoriale.">
<title>{title} — AURA</title>
<link rel="stylesheet" href="assets/aura.css"></head>
<body class="{page_class}">
<a class="skip" href="#main">Aller au contenu</a>
{body}
<script src="assets/app.js" defer></script>
</body></html>
'''


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def badge(b):
    kind = b["kind"]
    cls = {"free": "badge-free", "premium": "badge-premium", "soon": "badge-soon"}.get(kind, "")
    label = b["availability"]
    dot = '<span class="dot"></span>' if kind == "available" else ""
    return f'<span class="badge {cls}">{dot}{label}</span>'


def card(b, compact=False):
    pct = b["progress"]
    play_data = (f'data-title="{b["title"]}" data-author="{b["author"]}" '
                 f'data-cover="{cover_url(b["slug"])}"')
    if b["kind"] == "soon":
        listen = '<span class="card-listen" aria-disabled="true">Bientôt disponible</span>'
        play_data = ''
    else:
        listen = (f'<button type="button" class="card-listen js-play" {play_data}>'
                  f'{ic("play", "ic ic-sm ic-fill")} Écouter</button>')
    progress = ""
    if pct:
        progress = (f'<div class="progress-line"><i style="width:{pct}%"></i></div>'
                    f'<p class="progress-note">{pct} % écouté</p>')
    cls = "book-card card-soon" if b["kind"] == "soon" else "book-card"
    return f'''<article class="{cls}">
  <a class="card-cover" href="04-livre-detail.html" aria-label="Voir {b["title"]}">
    <img src="{cover_url(b["slug"])}" alt="Couverture de {b["title"]}">
    {badge(b)}
    {f'<span class="play-dot">{ic("play", "ic ic-fill")}</span>' if play_data else ''}
  </a>
  <div class="card-body">
    <a href="04-livre-detail.html"><h3 class="card-title">{b["title"]}</h3></a>
    <p class="card-author">{b["author"]}</p>
    <p class="card-meta">{ic("clock", "ic ic-sm")} {b["duration"]}<span class="sep"></span>{b["cat"]}</p>
    <div class="card-bottom">{listen}
      <button class="fav" aria-pressed="false" aria-label="Ajouter {b["title"]} aux favoris">
        <span class="fav-icon ic" aria-hidden="true">♡</span></button>
    </div>
    {progress}
  </div>
</article>'''


def remaining_text(b):
    """Remaining listening time, derived from duration and progress."""
    import re
    m = re.match(r"(\d+)\s*h\s*(\d+)", b["duration"])
    minutes = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
    left = round(minutes * (1 - b["progress"] / 100))
    return f"{left // 60} h {left % 60:02d}"


def resume_item(b):
    pct = b["progress"]
    remaining = remaining_text(b)
    return f'''<article class="resume-item">
  <div class="resume-cover"><img src="{cover_url(b["slug"])}" alt=""></div>
  <div class="resume-copy">
    <p class="eyebrow">En cours</p>
    <h3>{b["title"]}</h3>
    <p class="author">{b["author"]}</p>
    <div class="progress-line" style="width:100%"><i style="width:{pct}%"></i></div>
    <p class="left">{pct} % écouté · il reste {remaining}</p>
    <button class="btn btn-primary btn-sm js-play" data-title="{b["title"]}" data-author="{b["author"]}" data-cover="{cover_url(b["slug"])}">Reprendre</button>
  </div>
</article>'''


def section_head(title, lede="", link=None):
    link_html = f'<a class="link" href="{link[1]}">{link[0]} {ic("arrow", "ic ic-sm")}</a>' if link else ""
    lede_html = f'<p class="lede">{lede}</p>' if lede else ""
    return (f'<div class="section-head"><div><h2>{title}</h2>'
            f'{lede_html}</div>{link_html}</div>')


def grid(items, cls=""):
    return f'<div class="card-grid {cls}">' + "".join(card(b) for b in items) + "</div>"


def scroll_shelf(items):
    return '<div class="shelf-scroll">' + "".join(card(b) for b in items) + "</div>"


def search_block(value="", with_suggest=True):
    suggestions = ""
    if with_suggest:
        chips = ["Romans courts", "Moins d'une heure", "Poésie", "Lu par Claire Aubertin"]
        suggestions = ('<div class="search-suggest"><span>En ce moment :</span>' +
                       "".join(f'<button class="suggest-chip" type="button">{c}</button>' for c in chips) +
                       "</div>")
    return f'''<section class="search-section wrap" aria-label="Recherche principale">
  <form class="search-bar" action="06-recherche-etats.html" method="get" role="search">
    {ic("search", "ic ic-lg")}
    <input type="search" name="q" value="{value}" placeholder="Un titre, un auteur, une envie…" aria-label="Rechercher un livre, un auteur ou un thème">
    <button class="btn btn-primary" type="submit">Rechercher</button>
  </form>
  {suggestions}
</section>'''


CATEGORIES = ["Tout", "Romans", "Nouvelles", "Poésie", "Essais", "Jeunesse", "Documentaires"]


def cats(active="Tout", tools=True):
    parts = []
    for c in CATEGORIES:
        count = sum(1 for b in BOOKS if b["cat"] == c)
        count_html = f'<span class="count">{count}</span>' if c != "Tout" else ""
        parts.append(
            f'<button class="cat-chip" type="button" aria-pressed="{str(c == active).lower()}">'
            f'{c}{count_html}</button>'
        )
    chips = "".join(parts)
    tool_html = ""
    if tools:
        tool_html = f'''<div class="filter-tools">
      <button class="btn btn-quiet btn-sm" type="button">{ic("filter", "ic ic-sm")} Filtres</button>
      <select aria-label="Trier les livres"><option>Ordre éditorial</option><option>Titre A → Z</option><option>Durée croissante</option><option>Nouveautés</option></select>
      <div class="view-switch" role="group" aria-label="Mode d'affichage">
        <button type="button" data-view="grille" aria-pressed="true" aria-label="Vue grille">{ic("grid", "ic ic-sm")}</button>
        <button type="button" data-view="liste" aria-pressed="false" aria-label="Vue liste">{ic("list", "ic ic-sm")}</button>
      </div>
    </div>'''
    return f'<section class="cats wrap" aria-label="Catégories">{chips}{tool_html}</section>'


# ---------------------------------------------------------------------------
# 1 & 2 — Home
# ---------------------------------------------------------------------------
def home(mobile=False):
    if mobile:
        hero = f'''<section class="hero"><div class="wrap hero-grid">
          <div class="hero-figure"><div class="hero-stack">
            <div class="hero-cover"><img src="{cover_url("petit-prince")}" alt=""></div>
            <div class="hero-cover"><img src="{cover_url("la-peste")}" alt=""></div>
            <div class="hero-cover"><img src="{cover_url("madame-bovary")}" alt=""></div>
            <div class="hero-note"><p class="eyebrow">À commencer</p><p>Le Petit Prince, de Saint-Exupéry</p></div>
          </div></div>
          <div>
            <p class="eyebrow">Bibliothèque audio</p>
            <h1>Des histoires<br>qui vous <em>suivent</em>.</h1>
            <p class="lede">Une bibliothèque choisie, des voix qui donnent vie aux textes. Écoutez où vous voulez, reprenez quand vous voulez.</p>
            <div class="hero-actions"><a class="btn btn-primary" href="03-bibliotheque.html">Explorer la bibliothèque {ic("arrow", "ic ic-sm")}</a>
            <a class="link" href="04-livre-detail.html">Écouter un extrait</a></div>
          </div>
        </div></section>'''
    else:
        hero = f'''<section class="hero"><div class="wrap hero-grid">
          <div>
            <p class="eyebrow">La bibliothèque audio · Édition 2026</p>
            <h1>Des histoires<br>qui vous <em>suivent</em>.</h1>
            <p class="lede">Une bibliothèque choisie, des voix qui donnent vie aux textes. Un extrait pour découvrir, un compte pour tout écouter — et reprendre exactement là où vous vous êtes arrêté.</p>
            <div class="hero-actions"><a class="btn btn-primary" href="03-bibliotheque.html">Explorer la bibliothèque {ic("arrow", "ic ic-sm")}</a>
            <a class="link" href="04-livre-detail.html">Écouter un extrait</a></div>
            <p class="hero-caption">16 titres · 6 voix · une seule idée : prendre le temps.</p>
          </div>
          <div class="hero-figure"><div class="hero-stack">
            <div class="hero-cover"><img src="{cover_url("petit-prince")}" alt=""></div>
            <div class="hero-cover"><img src="{cover_url("la-peste")}" alt=""></div>
            <div class="hero-cover"><img src="{cover_url("madame-bovary")}" alt=""></div>
            <div class="hero-note"><p class="eyebrow">La voix du moment</p><p>« Une lecture qui laisse respirer chaque phrase. »</p></div>
          </div></div>
        </div></section>'''

    resume = f'''<section class="section section-tint" id="reprise"><div class="wrap">
      {section_head("Reprendre l'écoute", "Vos lectures en cours, à la dernière position.", ("Tout voir", "05-lecteur.html"))}
      <div class="resume-grid">''' + "".join(resume_item(b) for b in RESUME) + "</div></div></section>"

    pick = f'''<div class="pick editorial-pick">
      <div class="pick-cover"><img src="{cover_url("la-peste")}" alt="Couverture de La Peste"></div>
      <div>
        <p class="eyebrow">La sélection de la rédaction</p>
        <h3>La Peste</h3>
        <p class="lede">Albert Camus · lu par Camille Delcourt</p>
        <blockquote>« On ne se résigne pas à l'évidence quand on a, comme Camus, le sens du réel et celui de la pitié. »</blockquote>
        <p class="detail-summary">{FEATURED["summary"]}</p>
        <div class="facts"><span>{ic("clock", "ic ic-sm")} 8 h 42</span><span>{ic("headphones", "ic ic-sm")} Voix seule</span><span>{ic("book", "ic ic-sm")} Les classiques</span></div>
        <div class="detail-cta"><a class="btn btn-primary" href="04-livre-detail.html">Découvrir le livre {ic("arrow", "ic ic-sm")}</a>
        <button class="btn btn-outline js-play" data-title="La Peste" data-author="Albert Camus" data-cover="{cover_url("la-peste")}">{ic("play", "ic ic-sm ic-fill")} Écouter un extrait</button></div>
      </div>
    </div>'''

    discover = f'''<section class="section" id="decouvrir"><div class="wrap">
      {section_head("À découvrir", "Une sélection choisie pour varier vos prochaines écoutes.", ("Toute la sélection", "03-bibliotheque.html"))}
      {pick}
      {scroll_shelf(DISCOVER) if mobile else grid(DISCOVER)}
    </div></section>'''

    library = f'''<section class="section section-tint" id="tous"><div class="wrap">
      {section_head("La bibliothèque", "Tous les livres audio disponibles, dans l'ordre que vous choisissez.", ("Voir les 16 titres", "03-bibliotheque.html"))}
      {grid(ALL)}
    </div></section>'''

    body = (head("Accueil" if not mobile else "") if not mobile else mobile_head()) + \
        f'<main id="main">{hero}{search_block()}{cats()}{discover}{resume}{library}</main>' + \
        foot() + (mobile_nav("Accueil") if mobile else "") + mini_player()
    return doc("Accueil" if not mobile else "Accueil · Mobile", body)


# ---------------------------------------------------------------------------
# 3 — Full library
# ---------------------------------------------------------------------------
def library_page():
    body = head("Bibliothèque") + f'''<main id="main">
  <section class="page-head"><div class="wrap">
    <p class="eyebrow">Le catalogue</p>
    <h1>Toute la bibliothèque.</h1>
    <p class="lede">Des classiques aux nouvelles, des voix qui prennent le temps. Choisissez une catégorie, affinez, puis lancez l'écoute.</p>
  </div></section>
  <div class="sticky-tools"><div class="wrap">{search_block(with_suggest=False)}</div></div>
  <div class="wrap">
    <nav class="cats" aria-label="Catégories" style="padding-bottom:8px">
      {cats(active="Tout")}
    </nav>
    <div class="result-line" role="status"><span>12 livres affichés sur 16 · page 1 sur 2</span><span>Tri : ordre éditorial</span></div>
    <div data-grid>{grid(ALL)}</div>
    <nav class="pager" aria-label="Pages du catalogue">
      <a class="btn btn-quiet btn-sm" href="#">Précédent</a>
      <a class="num" href="#" aria-current="page">1</a><a class="num" href="#">2</a>
      <a class="btn btn-quiet btn-sm" href="#">Suivant</a>
    </nav>
  </div>
</main>''' + foot() + mini_player()
    return doc("Bibliothèque", body)


# ---------------------------------------------------------------------------
# 4 — Book detail
# ---------------------------------------------------------------------------
def detail_page():
    chapters = [
        ("I. La ville", "0:00"), ("II. La peste", "38:12"), ("III. La quarantaine", "1:34:05"),
        ("IV. Les messagers", "2:41:50"), ("V. Le sacrifice", "4:02:18"), ("VI. La fin", "6:58:44"),
    ]
    rows = "".join(
        f'<li><span class="n">{i:02d}</span><span class="t">{t}</span>'
        f'<span class="d">{d}</span><button class="js-play" data-title="La Peste — {t}" '
        f'data-author="Albert Camus" data-cover="{cover_url("la-peste")}" aria-label="Écouter {t}">{ic("play", "ic ic-sm ic-fill")}</button></li>'
        for i, (t, d) in enumerate(chapters, 1)
    )
    body = head("Bibliothèque") + f'''<main id="main">
  <div class="wrap">
    <nav class="crumbs" aria-label="Fil d'Ariane"><a href="03-bibliotheque.html">Bibliothèque</a><span>/</span>
      <a href="03-bibliotheque.html">Les classiques</a><span>/</span><span>La Peste</span></nav>
    <section class="detail-hero">
      <div class="detail-cover"><img src="{cover_url("la-peste")}" alt="Couverture de La Peste"></div>
      <div class="detail-info">
        <p class="eyebrow">Les classiques · roman</p>
        <h1>La Peste</h1>
        <p class="detail-author">de <a href="06-recherche-etats.html">Albert Camus</a></p>
        <div class="detail-facts">
          <span>{ic("clock", "ic ic-sm")} 8 h 42</span>
          <span>{ic("headphones", "ic ic-sm")} Lu par Camille Delcourt</span>
          <span>{ic("book", "ic ic-sm")} 6 chapitres</span>
          <span>{ic("check", "ic ic-sm")} Disponible</span>
        </div>
        <p class="detail-summary">{FEATURED["summary"]}</p>
        <div class="tag-row"><span class="tag">Roman</span><span class="tag">Français</span><span class="tag">Voix seule</span><span class="tag">{FEATURED["year"]}</span></div>
        <div class="detail-cta">
          <button class="btn btn-primary js-play" data-title="La Peste" data-author="Albert Camus" data-cover="{cover_url("la-peste")}">{ic("play", "ic ic-sm ic-fill")} Écouter le livre</button>
          <a class="btn btn-outline" href="05-lecteur.html">Ouvrir le lecteur</a>
          <button class="btn btn-quiet fav" aria-pressed="false" aria-label="Ajouter aux favoris"><span class="fav-icon ic">♡</span> Favori</button>
          <button class="btn btn-quiet">{ic("share", "ic ic-sm")} Partager</button>
        </div>
        <div class="preview-strip">
          <div>{ic("headphones", "ic ic-lg")}</div>
          <div><p class="eyebrow">Extrait gratuit</p><p>Une minute, sans compte.</p></div>
          <button class="btn btn-quiet btn-sm js-play" data-title="La Peste — extrait" data-author="Albert Camus" data-cover="{cover_url("la-peste")}">{ic("play", "ic ic-sm ic-fill")} Écouter</button>
        </div>
      </div>
    </section>
    <section class="section" style="border-top:1px solid var(--line-soft)">
      <div class="note-box"><h3>Avant de commencer</h3>
        <p>La peste s'installe à Oran. Le récit suit ceux qui restent, ceux qui partent et ceux qui, simplement, continuent. Rien n'est expliqué d'avance : laissez la voix vous conduire.</p>
      </div>
    </section>
    <section class="section"><div class="section-head"><div><h2>Chapitres</h2><p class="lede">Six mouvements, du premier jour au dernier.</p></div></div>
      <ol class="chapter-list">{rows}</ol>
    </section>
    <section class="section">
      {section_head("À écouter ensuite", "Quatre lectures dans la même veine.", ("Voir tout", "03-bibliotheque.html"))}
      {grid([BY_SLUG["etranger"], BY_SLUG["sous-soleil"], BY_SLUG["nouvelles"], BY_SLUG["lettres"]])}
    </section>
  </div>
</main>''' + foot() + mini_player()
    return doc("La Peste — Livre audio", body)


# ---------------------------------------------------------------------------
# 5 — Player
# ---------------------------------------------------------------------------
def player_page():
    ch_rows = [
        ("I. La ville", "0:00", False), ("II. La peste", "38:12", False),
        ("III. La quarantaine", "1:34:05", False), ("IV. Les messagers", "2:41:50", True),
        ("V. Le sacrifice", "4:02:18", False), ("VI. La fin", "6:58:44", False),
    ]
    rows = "".join(
        f'<div class="ch-row{" current" if cur else ""}"><span class="n">{i:02d}</span>'
        f'<span class="t">{t}</span><span class="d">{d}</span></div>'
        for i, (t, d, cur) in enumerate(ch_rows, 1)
    )
    body = f'''<header class="site-head"><div class="wrap head-inner">
      {brand()}<nav class="head-nav" aria-label="Navigation principale">
        <a href="01-accueil-desktop.html">Accueil</a><a href="03-bibliotheque.html">Bibliothèque</a>
        <a href="04-livre-detail.html">Le livre</a><a href="05-lecteur.html" aria-current="page">Lecteur</a></nav>
      <div class="head-end"><button class="icon-btn" aria-label="Rechercher">{ic("search")}</button>
      <span class="avatar" aria-hidden="true">CL</span><button class="icon-btn head-menu-toggle" aria-label="Ouvrir le menu">{ic("menu")}</button></div>
    </div></header>
    <main id="main"><div class="wrap player-stage">
      <div class="player-cover"><img src="{cover_url("la-peste")}" alt="Couverture de La Peste"></div>
      <div class="player-meta">
        <p class="eyebrow">En cours d'écoute</p>
        <h1>La Peste</h1>
        <p class="author">Albert Camus · lu par Camille Delcourt</p>
        <p class="chapter">Chapitre IV — Les messagers</p>
        <div class="seek-wrap">
          <input class="seek" type="range" min="0" max="100" value="38" aria-label="Position dans le livre" style="background:linear-gradient(90deg,#D6B67F 0 38%,rgba(255,255,255,.22) 38% 100%)">
          <div class="times"><span>3 h 19</span><span>Il reste 5 h 23</span></div>
        </div>
        <div class="transport" role="group" aria-label="Commandes de lecture">
          <button class="t-btn small" aria-label="Titre précédent">{ic("prev")}</button>
          <button class="t-btn small" aria-label="Reculer de 15 secondes">{ic("back")}</button>
          <button class="t-btn main" aria-label="Mettre en pause">{ic("pause-solid", "ic ic-lg")}</button>
          <button class="t-btn small" aria-label="Avancer de 15 secondes">{ic("fwd")}</button>
          <button class="t-btn small" aria-label="Titre suivant">{ic("next")}</button>
        </div>
        <div class="player-options">
          <button class="opt" aria-label="Vitesse de lecture">1× · Vitesse</button>
          <button class="opt" aria-label="Minuteur de sommeil">{ic("sleep", "ic ic-sm")} Sommeil</button>
          <button class="opt" aria-pressed="true">{ic("bookmark", "ic ic-sm")} Marque-pages</button>
          <button class="opt">{ic("queue", "ic ic-sm")} File d'attente</button>
          <button class="opt">{ic("volume", "ic ic-sm")} Volume</button>
        </div>
        <div class="player-chapters"><h2>Les chapitres</h2>{rows}</div>
      </div>
    </div></main>'''
    return doc("Lecteur audio", body, "player-page")


# ---------------------------------------------------------------------------
# 6 — Search & filter states
# ---------------------------------------------------------------------------
def states_page():
    results = f'''<div class="state-panel active" id="state-resultats" role="tabpanel" aria-labelledby="tab-resultats">
      <div class="result-line" role="status"><span><span data-echo-query>camus</span> — 2 livres trouvés</span><span>Tri : pertinence</span></div>
      <div class="active-filters"><span class="filter-pill">« <span data-echo-query>camus</span> »<button aria-label="Retirer">×</button></span>
        <span class="filter-pill">Romans<button aria-label="Retirer">×</button></span>
        <span class="filter-pill">Moins de 10 h<button aria-label="Retirer">×</button></span></div>
      {grid([BY_SLUG["la-peste"], BY_SLUG["etranger"]])}
    </div>'''
    empty = f'''<div class="state-panel" id="state-vide" role="tabpanel" aria-labelledby="tab-vide">
      <div class="state-card">
        <div class="state-ico">{ic("search", "ic ic-lg")}</div>
        <h2>Aucun livre trouvé</h2>
        <p>La recherche « <span data-echo-query>camus</span> », avec ces filtres, ne donne aucun résultat. Vérifiez l'orthographe, ou retirez un filtre pour élargir.</p>
        <div class="state-actions"><button class="btn btn-primary js-reset">Effacer les filtres</button>
          <a class="btn btn-outline" href="03-bibliotheque.html">Voir toute la bibliothèque</a></div>
        <p class="err-note">Suggestions : « Camus », « Albert Camus », « romans courts ».</p>
      </div>
    </div>'''
    sk_cards = "".join(
        '<div class="sk-card"><div class="sk sk-cover"></div>'
        '<div class="sk sk-line"></div><div class="sk sk-line short"></div></div>'
        for _ in range(8)
    )
    loading = '''<div class="state-panel" id="state-chargement" role="tabpanel" aria-labelledby="tab-chargement">
      <div class="result-line"><span>Recherche en cours…</span><span>Les résultats arrivent</span></div>
      <div class="skeleton-grid" aria-hidden="true">''' + sk_cards + '''</div>
      <p class="err-note" role="status">Chargement des résultats — la structure de la page reste stable.</p>
    </div>'''
    error = '''<div class="state-panel" id="state-erreur" role="tabpanel" aria-labelledby="tab-erreur">
      <div class="state-card">
        <div class="state-ico" style="background:var(--danger-soft);color:var(--danger)">''' + ic("alert", "ic ic-lg") + '''</div>
        <h2>La recherche n'a pas répondu</h2>
        <p>Le catalogue est momentanément indisponible. Votre recherche et vos filtres sont conservés — réessayez dans un instant.</p>
        <div class="state-actions"><button class="btn btn-primary">Réessayer</button>
          <a class="btn btn-outline" href="03-bibliotheque.html">Retour à la bibliothèque</a></div>
        <p class="err-note">Aucune donnée n'a été perdue. Si le problème persiste, contactez-nous.</p>
      </div>
    </div>'''
    tabs = "".join(
        f'<button class="state-tab" type="button" id="tab-{key}" role="tab" data-state="{key}" '
        f'aria-controls="state-{key}" aria-selected="{str(key == "resultats").lower()}">{label}</button>'
        for key, label in (("resultats", "Résultats"), ("vide", "État vide"),
                           ("chargement", "Chargement"), ("erreur", "Erreur"))
    )
    body = head("Bibliothèque") + f'''<main id="main">
  <section class="page-head"><div class="wrap">
    <p class="eyebrow">Recherche & filtres</p>
    <h1>Trouver le bon livre.</h1>
    <p class="lede">Quatre états d'une même page : résultats, aucun résultat, chargement et erreur. La recherche reste lisible à chaque étape.</p>
  </div></section>
  <div class="wrap">
    <nav class="state-tabs" role="tablist" aria-label="États de recherche">{tabs}</nav>
    {search_block(value="camus", with_suggest=False)}
    {cats(active="Romans")}
    {results}{empty}{loading}{error}
  </div>
</main>''' + foot() + mini_player()
    return doc("États de recherche", body)


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------
def design_system():
    swatches = [
        ("Papier ivoire", "#F7F4ED", "Fond général"), ("Papier haut", "#FBF9F4", "Surfaces"),
        ("Sable", "#E6DDCE", "Détails, pistes"), ("Encre nuit", "#142438", "Titres, actions"),
        ("Bleu nuit 2", "#223754", "Survol, nuit"), ("Texte", "#26313D", "Corps de texte"),
        ("Terre cuite", "#9C5F42", "Accent éditorial"), ("Ocre", "#885F26", "Accent, focus"),
        ("Sauge", "#5E735F", "Disponible"), ("Laiton clair", "#D6B67F", "Lecteur"),
        ("Trait", "#DCD3C4", "Séparateurs"), ("Erreur", "#93493F", "États d'erreur"),
    ]
    sw = "".join(
        f'<div class="swatch"><div class="chip" style="background:{hexv}"></div>'
        f'<div class="lab"><strong>{name}</strong><span>{hexv} · {role}</span></div></div>'
        for name, hexv, role in swatches
    )
    types = [
        ("Affichage", "Instrument Serif · 82 / 1.02", "Des histoires qui vous suivent."),
        ("Titre de section", "Instrument Serif · 42 / 1.10", "À découvrir"),
        ("Titre de carte", "Instrument Serif · 21 / 1.18", "Madame Bovary"),
        ("Interface", "Jakarta · 16 / 1.60", "Une bibliothèque choisie, des voix qui donnent vie aux textes."),
        ("Métadonnées", "Jakarta · 13 / 1.50", "8 h 42 · Romans · Lu par Camille Delcourt"),
        ("Sur titre", "Jakarta 700 · 11 / .19em", "BIBLIOTHÈQUE AUDIO"),
    ]
    rows = "".join(
        f'<div class="type-row{" ui" if i >= 3 else ""}"><span class="spec">{name}<br><span style="letter-spacing:0">{spec}</span></span>'
        f'<span class="sample">{sample[:44]}</span></div>'
        for i, (name, spec, sample) in enumerate(types)
    )
    tokens = [
        ("Espace", "--s1 … --s9", "4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 px"),
        ("Rayon", "--r-sm … --r-xl", "4 · 8 · 14 · 22 px ; pilules 999 px"),
        ("Colonnes", "grille", "4 (desktop) · 3 (tablette) · 2 (mobile)"),
        ("Largeur", "--wrap", "1 240 px, gouttières 24 / 32 px"),
        ("Ombre", "--sh-1 … --sh-3", "diffuse, jamais colorée"),
        ("Focus", "--ochre", "contour 3 px, décalage 3 px"),
    ]
    trs = "".join(f'<tr><td>{a}</td><td><code>{b}</code></td><td>{c}</td></tr>' for a, b, c in tokens)
    comps = f'''<div class="demo-row"><span class="demo-label">Bouton principal</span><button class="btn btn-primary">Écouter le livre</button><button class="btn btn-primary" disabled style="opacity:.45">Désactivé</button></div>
    <div class="demo-row"><span class="demo-label">Bouton secondaire</span><button class="btn btn-outline">Ouvrir le lecteur</button><button class="btn btn-quiet">Favori</button></div>
    <div class="demo-row"><span class="demo-label">Lien</span><a class="link" href="#">Voir la bibliothèque {ic("arrow", "ic ic-sm")}</a><a class="link-plain" href="#">Effacer les filtres</a></div>
    <div class="demo-row"><span class="demo-label">Pastilles</span><span class="badge" style="position:static"><span class="dot"></span>Disponible</span><span class="badge badge-free" style="position:static">Extrait gratuit</span><span class="badge badge-premium" style="position:static">Premium</span><span class="badge badge-soon" style="position:static">Bientôt</span></div>
    <div class="demo-row"><span class="demo-label">Catégories</span><button class="cat-chip" aria-pressed="true">Romans</button><button class="cat-chip">Poésie <span class="count">2</span></button></div>
    <div class="demo-row"><span class="demo-label">Champ de recherche</span><div class="search-bar" style="max-width:460px;flex:1">{ic("search")}<input placeholder="Un titre, un auteur…" aria-label="Exemple de recherche"></div></div>
    <div class="demo-row"><span class="demo-label">Progression</span><div style="width:220px"><div class="progress-line"><i style="width:42%"></i></div><p class="progress-note">42 % écouté · il reste 5 h 58</p></div></div>'''
    body = head() + f'''<main id="main">
    <section class="ds-hero"><div class="wrap">
      <p class="eyebrow">Fondations</p>
      <h1>Le système AURA.</h1>
      <p class="lede">Sept règles, une seule ambition : une bibliothèque éditoriale où l'information respire et où l'écoute reste l'action la plus évidente.</p>
    </div></section>
    <nav class="ds-nav"><div class="wrap"><a href="#couleurs">Couleurs</a><a href="#type">Typographie</a><a href="#tokens">Rythme & grille</a><a href="#composants">Composants</a><a href="#regles">Règles d'usage</a><a href="#responsive">Responsive</a></div></nav>

    <section class="ds-section" id="couleurs"><div class="wrap">
      <h2>Couleurs</h2><p class="lede">Ivoire et papier pour le fond, bleu nuit pour l'encre et les actions. Les accents naturels restent rares : un seul par écran.</p>
      <div class="swatch-grid">{sw}</div>
    </div></section>

    <section class="ds-section" id="type"><div class="wrap">
      <h2>Typographie</h2><p class="lede">Deux voix seulement : un serif éditorial pour les titres et la citation, un sans contemporain pour l'interface. Aucune troisième famille.</p>
      {rows}
    </div></section>

    <section class="ds-section" id="tokens"><div class="wrap">
      <h2>Rythme & grille</h2><p class="lede">Une échelle d'espacement unique et une grille à quatre colonnes. Les écarts entre sections sont toujours plus grands qu'à l'intérieur d'une section.</p>
      <table class="token-table"><thead><tr><th>Token</th><th>Valeur</th><th>Usage</th></tr></thead><tbody>{trs}</tbody></table>
    </div></section>

    <section class="ds-section" id="composants"><div class="wrap">
      <h2>Composants fondamentaux</h2><p class="lede">Boutons, pastilles, catégories, champ de recherche et progression. Chaque état est dessiné, y compris le désactivé.</p>
      {comps}
    </div></section>

    <section class="ds-section" id="regles"><div class="wrap">
      <h2>Règles d'usage</h2><p class="lede">Ce qui fait la tenue du système — et ce qui la casseraient.</p>
      <div class="rule-grid">
        <div class="rule-card"><h3>{ic("check", "ic ic-sm")} À faire</h3><ul>
          <li>Un seul sujet par écran ; tout le reste se tait.</li>
          <li>Couverture en 2:3, coins presque carrés, ombre très légère.</li>
          <li>Titre serif, action en bleu nuit, accent naturel ponctuel.</li>
          <li>Libellés complets : « Écouter », « Reprendre », « Effacer les filtres ».</li>
          <li>États vides, chargement et erreur dessinés comme les autres.</li>
        </ul></div>
        <div class="rule-card bad"><h3>{ic("close", "ic ic-sm")} À éviter</h3><ul>
          <li>Cartes denses, corps de texte sous 13 px, jargon management.</li>
          <li>Surcouches colorées sur les couvertures au repos.</li>
          <li>Logos de plateformes de streaming, dégradés, néons.</li>
          <li>Icônes émoji ; utiliser les tracés SVG fournis.</li>
          <li>Empiler les accents : terre cuite et ocre sur le même écran.</li>
        </ul></div>
      </div>
    </div></section>

    <section class="ds-section" id="responsive"><div class="wrap">
      <h2>Responsive</h2><p class="lede">Le nombre de colonnes suit l'espace disponible, pas l'inverse. Sur mobile, la navigation devient une barre basse et l'écoute reste à portée de pouce.</p>
      <table class="token-table"><thead><tr><th>Environnement</th><th>Colonnes</th><th>Navigation</th><th>Priorité</th></tr></thead><tbody>
        <tr><td>Desktop · ≥ 1 101 px</td><td>4</td><td>Barre haute complète</td><td>Découverte + bibliothèque</td></tr>
        <tr><td>Tablette · 561 – 1 100 px</td><td>3</td><td>Barre haute complète</td><td>Grille adaptée</td></tr>
        <tr><td>Mobile · ≤ 560 px</td><td>2</td><td>Barre basse à 5 entrées</td><td>Consultation et écoute</td></tr>
      </tbody></table>
    </div></section>
</main>''' + foot()
    return doc("Système de design", body)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
def index_page():
    items = [
        ("01", "Page d'accueil — Desktop", "Hero éditorial, recherche, catégories, sélection, reprise, bibliothèque.", "01-accueil-desktop.html"),
        ("02", "Page d'accueil — Mobile", "La même promesse, une navigation basse et des cartes qui restent lisibles.", "02-accueil-mobile.html"),
        ("03", "Vue complète de la bibliothèque", "Recherche collante, filtres actifs, grille et pagination.", "03-bibliotheque.html"),
        ("04", "Page de détail d'un livre", "Couverture, résumé, chapitres, extrait et actions claires.", "04-livre-detail.html"),
        ("05", "Interface du lecteur audio", "Vue d'écoute plein écran, transport, options et chapitres.", "05-lecteur.html"),
        ("06", "États de recherche et de filtrage", "Résultats, vide, chargement, erreur — via les onglets ou ?state=.", "06-recherche-etats.html"),
        ("DS", "Système de design", "Couleurs, typographie, rythme, composants et règles d'usage.", "design-system.html"),
    ]
    cards = "".join(
        f'<a class="index-card" href="{href}"><span class="num">{n}</span><h2>{title}</h2><p>{desc}</p></a>'
        for n, title, desc, href in items
    )
    body = f'''<main id="main"><div class="wrap index-hero">
    <p class="eyebrow">Mission design · Refonte UX/UI</p>
    <h1>AURA, bibliothèque audio.</h1>
    <p class="lede">Une refonte éditoriale : fond ivoire, encre bleu nuit, couvertures originales et une seule idée — que l'écoute commence en un geste. Prototype haute fidélité, données illustratives.</p>
  </div><div class="wrap index-grid">{cards}</div></main>'''
    return doc("AURA — Prototype", body)


# ---------------------------------------------------------------------------
PAGES = {
    "index.html": index_page,
    "01-accueil-desktop.html": lambda: home(False),
    "02-accueil-mobile.html": lambda: home(True),
    "03-bibliotheque.html": library_page,
    "04-livre-detail.html": detail_page,
    "05-lecteur.html": player_page,
    "06-recherche-etats.html": states_page,
    "design-system.html": design_system,
}

for name, builder in PAGES.items():
    (ROOT / name).write_text(builder(), encoding="utf-8")

print(f"Built {len(PAGES)} pages in {ROOT}")
