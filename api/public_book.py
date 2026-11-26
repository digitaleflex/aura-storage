"""HTML of the browsable (signed-out) part of the public portal.

Landing page with the published catalogue, and one page per book with a free
preview, chapters and share links. Same rules as public_ui: no inline script,
no external resource, so the strict portal CSP applies unchanged.
"""
import json
from urllib.parse import quote, quote_plus, urlencode

from .public_ui import (
    ESC, SORTS, _BRAND, _GOOGLE, _SKIP_LINK, _duration_text, _heart_button, _position_text, asset_url,
    cover_hue, email_form, fallback_cover_inner, page_head,
)

SITE_NAME = "AURA"


def book_path(item: dict) -> str:
    return f"/livre/{item['id']}"


def _cover(item: dict) -> str:
    label = str(item.get("title") or item.get("display_name") or "Livre")
    inner = fallback_cover_inner(label, item.get("author") or "")
    if item.get("cover_url"):
        inner += f'<img src="{ESC(item["cover_url"])}" alt="" loading="lazy" data-fallback>'
    return (
        f'<span class="cover cover-large" style="--cover-h:{cover_hue(label)}" '
        f'aria-hidden="true">{inner}</span>'
    )


def _card(item: dict) -> str:
    label = str(item.get("title") or item.get("display_name") or "Livre")
    return "".join([
        '<li class="book-card"><a href="', ESC(book_path(item)), '">',
        _cover(item),
        f'<span class="book-card-title">{ESC(label)}</span>',
        f'<span class="book-card-author">{ESC(item.get("author") or "Livre audio")}</span>',
        f'<span class="book-card-meta">{ESC(_duration_text(item.get("duration_seconds")))}</span>',
        '</a></li>',
    ])


def _brand_bar(principal: dict | None) -> str:
    right = (
        '<a class="text-button" href="/">Ma bibliothèque</a>'
        if principal else
        '<a class="text-button" href="/api/public/auth/google">Se connecter</a>'
    )
    return (
        '<header class="topbar"><a class="brand" href="/" aria-label="Accueil">'
        + _BRAND + '<span class="word">AURA</span></a><div class="member">'
        + right + '</div></header>'
    )


def landing_page(
    collections: list[dict], query: str = "", authors: list[str] | None = None,
    active_author: str = "", base_url: str = "", with_email: bool = False, sort: str = "",
    search_note: str = "",
    facet_options: dict | None = None,
    active_facets: dict | None = None,
    filter_error: str = "",
    page: int = 1,
    page_size: int = 24,
) -> str:
    """Anonymous front page: the catalogue to browse, a clear way to sign in."""
    authors = authors or []
    facet_options = facet_options or {}
    active_facets = active_facets or {}
    items = [i for col in collections for i in col.get("items", [])]
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 24), 60))
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]
    description = (
        f"{len(items)} livres audio à découvrir : écoutez un extrait gratuit, "
        "puis entrez avec Google pour tout écouter."
    )
    meta = [
        ("property", "og:type", "website"), ("property", "og:site_name", SITE_NAME),
        ("property", "og:title", "AURA — Bibliothèque de livres audio"),
        ("property", "og:description", description), ("property", "og:locale", "fr_FR"),
        ("name", "twitter:card", "summary"),
    ]
    if base_url:
        meta.append(("property", "og:url", base_url + "/"))
    parts = [
        page_head("AURA — Bibliothèque de livres audio", description, meta),
        '</head><body>', _SKIP_LINK, _brand_bar(None),
        '<main class="library view-grille" id="main">',
        '<section class="welcome"><p class="kicker">Bibliothèque audio</p>',
        '<h1>Des livres à écouter, <span class="nowrap">où que vous soyez.</span></h1>',
        f'<p class="lede">{len(items)} titres. Un extrait gratuit sur chaque livre ; '
        'votre compte Google suffit pour tout écouter et reprendre là où vous vous êtes arrêté.</p>',
        '<p class="welcome-actions"><a class="google-button" href="/api/public/auth/google">',
        _GOOGLE, '<span>Continuer avec Google</span></a></p>',
        email_form() if with_email else '', '</section>',
        '<form class="search-form" method="get" action="/">',
        f'<input type="search" name="q" value="{ESC(query)}" '
        'placeholder="Rechercher un livre, un auteur…" aria-label="Rechercher un livre, un auteur">',
    ]
    if authors:
        parts.append('<select name="auteur" aria-label="Auteur"><option value="">Tous les auteurs</option>')
        for a in authors:
            sel = " selected" if a == active_author else ""
            parts.append(f'<option value="{ESC(a)}"{sel}>{ESC(a)}</option>')
        parts.append('</select>')
    parts.append('<select name="tri" aria-label="Tri">')
    for label, value in SORTS:
        parts.append(f'<option value="{ESC(value)}"{" selected" if value == sort else ""}>{ESC(label)}</option>')
    parts.append('</select><button type="submit">Rechercher</button></form>')
    if search_note:
        parts.append(f'<p class="search-note" role="status">Compris comme : {ESC(search_note)}</p>')
    if query or active_author or sort:
        parts.append('<p class="filters-reset"><a class="facet-clear" href="/">Effacer les filtres</a></p>')
    if not items:
        parts.append('<p class="empty">Aucun livre ne correspond à votre recherche.</p>')
    else:
        title = collections[0]["title"] if len(collections) == 1 else "Tous les livres"
        parts.append(f'<section class="shelf"><div class="shelf-head"><h2>{ESC(title)}</h2>'
                     f'<p class="desc">Page {page} sur {pages} · {total} titre{"s" if total != 1 else ""}</p>'
                     '</div><ul class="book-grid catalog-grid">')
        parts.extend(_card(i) for i in page_items)
        parts.append('</ul>')
        if pages > 1:
            def _page_href(pn: int) -> str:
                qs = []
                if query: qs.append(f"q={quote_plus(query)}")
                if active_author: qs.append(f"auteur={quote_plus(active_author)}")
                if sort: qs.append(f"tri={quote_plus(sort)}")
                for k, v in (("collection", active_facets.get("collection")), ("categorie", active_facets.get("category")), ("theme", active_facets.get("theme")), ("langue", active_facets.get("language")), ("format", active_facets.get("format")), ("duree_min", active_facets.get("duration_min")), ("duree_max", active_facets.get("duration_max"))):
                    if v: qs.append(f"{k}={quote_plus(str(v))}")
                if pn > 1: qs.append(f"page={pn}")
                return "/?" + "&".join(qs) if qs else "/"
            parts.append('<nav class="pagination" aria-label="Pagination">')
            if page > 1:
                parts.append(f'<a class="page-link" href="{ESC(_page_href(page-1))}">Précédent</a>')
            for pn in range(1, pages+1):
                if pn == 1 or pn == pages or abs(pn-page) <= 2:
                    cur = ' aria-current="page"' if pn == page else ''
                    parts.append(f'<a class="page-link" href="{ESC(_page_href(pn))}"{cur}>{pn}</a>')
                elif abs(pn-page) == 3:
                    parts.append('<span class="page-ellipsis">…</span>')
            if page < pages:
                parts.append(f'<a class="page-link" href="{ESC(_page_href(page+1))}">Suivant</a>')
            parts.append('</nav>')
        parts.append('</section>')
    parts.append('</main><footer class="site-foot">AURA · Écoute privée</footer></body></html>')
    return "".join(parts)


def book_page(
    item: dict, collection_title: str, related: list[dict],
    principal: dict | None, base_url: str = "", preview_seconds: int = 0,
    up_next: list[dict] | None = None,
    recap: str = "",
    series_position: int = 0,
    series_total: int = 0,
) -> str:
    """One book: cover, facts, free preview, chapters, sign-in / listen call to action."""
    label = str(item.get("title") or item.get("display_name") or "Livre")
    author = str(item.get("author") or "")
    duration = float(item.get("duration_seconds") or 0)
    chapters = item.get("chapters") or []
    url = base_url + book_path(item)
    summary = f"{label}" + (f", de {author}" if author else "")
    description = (
        f"{summary} — livre audio de {_duration_text(duration)}. "
        + (f"Écoutez un extrait de {preview_seconds // 60 or 1} min gratuitement." if preview_seconds else "Écoutez-le sur AURA.")
    )
    meta = [
        ("property", "og:type", "book"), ("property", "og:site_name", SITE_NAME),
        ("property", "og:title", f"{label} — {SITE_NAME}"),
        ("property", "og:description", description), ("property", "og:locale", "fr_FR"),
        ("name", "twitter:card", "summary_large_image" if item.get("cover_url") else "summary"),
        ("name", "twitter:title", f"{label} — {SITE_NAME}"),
        ("name", "twitter:description", description),
    ]
    if base_url:
        meta.append(("property", "og:url", url))
    if base_url and item.get("cover_url"):
        meta.append(("property", "og:image", base_url + item["cover_url"]))
        meta.append(("name", "twitter:image", base_url + item["cover_url"]))
    ld = {
        "@context": "https://schema.org", "@type": "Audiobook", "name": label,
        "inLanguage": "fr", "url": url,
    }
    if author:
        ld["author"] = {"@type": "Person", "name": author}
    if duration:
        ld["duration"] = f"PT{int(duration)}S"
    if principal:
        meta.append(("name", "csrf-token", str(principal.get("csrf") or "")))
    parts = [page_head(f"{label} — {SITE_NAME}", description, meta)]
    if base_url:
        parts.append(f'<link rel="canonical" href="{ESC(url)}">')
    parts.append('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + '</script>')
    parts += ['</head><body>', _SKIP_LINK, _brand_bar(principal), '<main class="library book" id="main">',
              '<p class="crumbs"><a href="/">← Toute la bibliothèque</a></p>',
              '<article class="book-hero">', _cover(item), '<div class="book-info">',
              f'<h1>{ESC(label)}</h1>']
    if author:
        parts.append(f'<p class="book-author"><a href="/?{ESC(urlencode({"auteur": author}))}">{ESC(author)}</a></p>')
    facts = [_duration_text(duration)] + ([f"{len(chapters)} chapitres"] if chapters else [])
    if collection_title:
        facts.append(collection_title)
    if series_total:
        facts.append(f"Tome {series_position} sur {series_total}")
    parts.append('<p class="book-facts">' + " · ".join(ESC(f) for f in facts) + '</p>')
    if preview_seconds:
        parts += [
            '<div class="preview"><p class="eyebrow">Extrait gratuit · 1 min, sans compte</p>',
            f'<audio controls controlsList="nodownload" disablePictureInPicture '
            f'preload="none" src="/extrait/{ESC(item["id"])}">'
            'Votre navigateur ne sait pas lire l’audio.</audio></div>',
        ]
    if principal:
        parts.append(f'<p class="book-cta"><a class="primary-button" href="/?lecture={ESC(item["id"])}">'
                     'Écouter le livre</a></p>')
    else:
        parts += [
            '<p class="book-cta"><a class="google-button" href="/api/public/auth/google">', _GOOGLE,
            '<span>Continuer avec Google pour écouter en entier</span></a></p>',
            '<p class="fine">Gratuit · aucun mot de passe à créer.</p>',
        ]
    parts += [
        '<p class="share">' + (_heart_button(item, label=True) if principal else '')
        + '<span class="label">Partager</span> ',
        f'<a class="pill" href="https://wa.me/?text={ESC(quote(label + " " + url))}" rel="noopener noreferrer" target="_blank">WhatsApp</a> ',
        f'<button type="button" class="pill" data-copy="{ESC(url or book_path(item))}">Copier le lien</button></p>',
        '</div></article>',
    ]
    if chapters:
        parts.append('<section class="shelf"><div class="shelf-head"><h2>Chapitres</h2></div><ol class="chapter-list">')
        for ch in chapters:
            parts.append(
                f'<li><span class="chapter-name">{ESC(ch.get("title") or "Chapitre")}</span>'
                f'<span class="chapter-time">{ESC(_position_text(ch.get("start_seconds")))}</span></li>'
            )
        parts.append('</ol></section>')
    if related:
        parts.append('<section class="shelf"><div class="shelf-head"><h2>Du même auteur</h2></div><ul class="book-grid">')
        parts.extend(_card(i) for i in related)
        parts.append('</ul></section>')
    if recap:
        parts.append(
            '<section class="recap" aria-labelledby="recap-title">'
            '<div class="shelf-head"><h2 id="recap-title">Avant de continuer</h2>'
            '<p class="desc">Résumé de la série, sans spoiler.</p></div>'
            f'<p>{ESC(recap)}</p></section>'
        )
    if up_next:
        parts.append('<section class="shelf"><div class="shelf-head"><h2>À écouter ensuite</h2>'
                     + (f'<p class="desc">Dans « {ESC(collection_title)} ».</p>' if collection_title else "")
                     + '</div><ul class="book-grid">')
        parts.extend(_card(i) for i in up_next)
        parts.append('</ul></section>')
    if principal:
        parts.append('<script src="' + asset_url("favorites.js") + '"></script>')
    if preview_seconds:
        parts.append('<script src="' + asset_url("preview.js") + '"></script>')
    parts.append('</main><footer class="site-foot">AURA · Écoute privée</footer></body></html>')
    return "".join(parts)


def confirm_login_page(token: str) -> str:
    """Landing of the mailed link: one button, so a mail scanner cannot use the link up."""
    return "".join([
        page_head(f"Connexion — {SITE_NAME}"), '</head><body>', _SKIP_LINK, _brand_bar(None),
        '<main class="library" id="main"><header class="library-header"><h1>Entrer dans la bibliothèque</h1>',
        '<p class="lede">Confirmez pour ouvrir votre session sur cet appareil.</p></header>',
        '<form method="post" action="/api/public/auth/email/confirm">',
        f'<input type="hidden" name="token" value="{ESC(token)}">',
        '<button class="primary-button" type="submit">Me connecter</button></form></main></body></html>',
    ])


def message_page(title: str, text: str) -> str:
    return "".join([
        page_head(f"{title} — {SITE_NAME}"), '</head><body>', _SKIP_LINK, _brand_bar(None),
        f'<main class="library" id="main"><header class="library-header"><h1>{ESC(title)}</h1>',
        f'<p class="lede">{ESC(text)}</p></header><p><a class="text-button" href="/">'
        'Retour à la bibliothèque</a></p></main></body></html>',
    ])
