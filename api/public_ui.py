"""HTML for the public portal.

Deliberately dependency-free: pages are served by the API on the public host,
with no JavaScript bundle and no external font/CDN. Styles and scripts live in
``api/portal_assets/`` and are served as same-origin files, so the portal can
run under a strict Content-Security-Policy (no inline script or <style>). The visual direction is a
warm library — ivory paper, night ink, brass accents, one clear action.
"""
import hashlib
import html
import json
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

_ASSET_DIR = Path(__file__).with_name("portal_assets")
_ASSET_TYPES = {
    ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml",
}


def _load_assets() -> dict:
    """``{name: (bytes, content_type, version)}`` read once at import time."""
    assets = {}
    for path in sorted(_ASSET_DIR.iterdir()):
        ctype = _ASSET_TYPES.get(path.suffix)
        if ctype:
            data = path.read_bytes()
            assets[path.name] = (data, ctype, hashlib.sha256(data).hexdigest()[:10])
    return assets


ASSETS = _load_assets()


def asset_url(name: str) -> str:
    """Versioned URL: the content hash changes with the file, so it can be cached for a year."""
    return f"/portal-assets/{name}?v={ASSETS[name][2]}"


ESC = lambda value: html.escape(str(value if value is not None else ""), quote=True)

_BRAND = (
    '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">'
    '<path d="M5 8.5h8.5a2 2 0 0 1 2 2V25H7a2 2 0 0 1-2-2V8.5Z"/>'
    '<path d="M27 8.5h-8.5a2 2 0 0 0-2 2V25H25a2 2 0 0 0 2-2V8.5Z"/>'
    '<path d="M11 14.5h3M18 14.5h3M11 18.5h3M18 18.5h3"/>'
    '</svg>'
)

_GOOGLE = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92'
    'c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09Z"/>'
    '<path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77'
    'c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84'
    'C3.99 20.53 7.7 23 12 23Z"/>'
    '<path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09'
    'V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22Z"/>'
    '<path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15'
    'C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84'
    'C6.71 7.31 9.14 5.38 12 5.38Z"/>'
    '</svg>'
)

# Installable app: manifest, icons and theme colour. The public portal is
# deliberately light-only, so the address bar keeps the light brand colour.
_PWA_TAGS = (
    '<meta name="theme-color" content="#F8F6F1">'
    '<link rel="manifest" href="' + asset_url("manifest.webmanifest") + '">'
    '<link rel="icon" href="' + asset_url("icon.svg") + '" type="image/svg+xml">'
    '<link rel="apple-touch-icon" href="' + asset_url("icon-192.png") + '">'
)

# Keyboard users must be able to skip the branded header on every page.
_SKIP_LINK = '<a class="skip-link" href="#main">Aller au contenu</a>'

# Human wording for the reasons produced by the audiobook scoring engine.
_REASON_LABELS = {
    "preferred_author": "Vous aimez cet auteur",
    "preferred_language": "Dans votre langue",
    "preferred_category": "Selon vos goûts",
    "preferred_narrator": "Vous connaissez ce narrateur",
    "preferred_duration": "La durée vous convient",
    "favorite_signal": "Proche de vos favoris",
    "in_progress_signal": "Vous avez commencé un livre similaire",
    "recent_catalog": "Nouveauté de la bibliothèque",
}

_HEAD = (
    '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + _PWA_TAGS +
    '<link rel="stylesheet" href="' + asset_url("portal.css") + '">'
    '<script defer src="' + asset_url("common.js") + '"></script>'
    '</head><body>' + _SKIP_LINK
)


def _title(title: str) -> str:
    return f'<title>{ESC(title)}</title>'


def page_head(title: str, description: str = "", meta: list | None = None) -> str:
    """Head with SEO/share metadata. ``meta`` is a list of (attribute, name, content)."""
    tags = [
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        _title(title),
    ]
    if description:
        tags.append(f'<meta name="description" content="{ESC(description)}">')
    for attr, name, content in meta or []:
        tags.append(f'<meta {attr}="{ESC(name)}" content="{ESC(content)}">')
    tags.append(_PWA_TAGS)
    tags.append('<link rel="stylesheet" href="' + asset_url("portal.css") + '">')
    tags.append('<script defer src="' + asset_url("common.js") + '"></script>')
    return "".join(tags)


def email_form(next_label: str = "Ou recevez un lien par e-mail") -> str:
    """Sign-in by mailed link; only shown when the server can send mail."""
    return (
        '<form class="email-form" method="post" action="/api/public/auth/email">'
        f'<label for="email">{ESC(next_label)}</label>'
        '<div class="email-row"><input id="email" type="email" name="email" required '
        'autocomplete="email" inputmode="email" maxlength="254" placeholder="vous@exemple.fr">'
        '<button type="submit">Recevoir le lien</button></div></form>'
    )


def login_page(with_email: bool = False) -> str:
    return _HEAD + _title("AURA — Votre bibliothèque audio") + """
<div class="stage">
  <main class="intro">
    <div class="brand">""" + _BRAND + """<span class="word">AURA</span></div>
    <p class="kicker">Bibliothèque audio privée</p>
    <h1>Votre bibliothèque,<br><span class="nowrap">à l'écoute.</span></h1>
    <p class="lede">Vos livres audio et vos enregistrements préférés, réunis au même
    endroit, prêts à vous suivre partout.</p>
    <div class="wave" aria-hidden="true">
      <i></i><i></i><i></i><i></i><i></i><i></i><i></i>
    </div>
  </main>
  <section class="access" aria-labelledby="access-title">
    <div class="panel">
      <p class="eyebrow">Accès membre</p>
      <h2 id="access-title">Entrez dans votre bibliothèque</h2>
      <p class="hint">Un seul geste : votre compte Google. Aucun mot de passe
      à créer, aucun formulaire à remplir.</p>
      <a class="google-button" href="/api/public/auth/google"
         aria-label="Continuer avec Google">""" + _GOOGLE + """
        <span>Continuer avec Google</span>
      </a>
      <p class="fine">Connexion sécurisée · Vos lectures restent privées.</p>
      """ + (email_form() if with_email else "") + """
    </div>
    <div class="rule" aria-hidden="true"><span></span><i></i><span></span></div>
    <p class="foot">AURA · Écoute privée</p>
  </section>
</div>
</body></html>"""


def profile_page(
    principal: dict, message: str = "", error: str = "",
    playlists: list | None = None, stats: dict | None = None,
) -> str:
    display_name = str(principal.get("display_name") or "")
    email = str(principal.get("email") or "")
    csrf = str(principal.get("csrf") or "")
    name = display_name or email or "Auditeur"
    notice = ""
    if message:
        notice = f'<p class="notice notice-ok" role="status">{ESC(message)}</p>'
    elif error:
        notice = f'<p class="notice notice-err" role="alert">{ESC(error)}</p>'
    return "".join([
        _HEAD,
        _title("AURA — Mon profil"),
        '<header class="topbar"><div class="brand">', _BRAND,
        '<span class="word">AURA</span></div><div class="member">',
        f'<span class="member-name">{ESC(name)}</span>',
        '<a class="text-button" href="/">Bibliothèque</a>',
        '<form method="post" action="/api/public/logout">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<button class="text-button" type="submit">Déconnexion</button>',
        '</form></div></header>',
        '<main class="profile-shell" id="main">',
        '<a class="back-link" href="/">← Retour à la bibliothèque</a>',
        '<header class="library-header profile-head"><h1>Mon profil</h1>',
        '<p class="lede">Gérez vos informations personnelles sur le portail.</p></header>',
        notice,
        '<section class="profile-card" aria-labelledby="profile-info-title">',
        '<h2 id="profile-info-title">Informations personnelles</h2>',
        '<p>L’email est fourni par votre compte Google et reste en lecture seule.</p>',
        '<form class="profile-form" method="post" action="/profil">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<div class="profile-field"><label for="display_name">Nom d’affichage</label>',
        f'<input id="display_name" name="display_name" type="text" maxlength="80" autocomplete="name" value="{ESC(display_name)}" placeholder="Votre nom d’affichage"></div>',
        '<div class="profile-field"><label for="email">Email</label>',
        f'<input id="email" name="email" type="email" value="{ESC(email)}" readonly></div>',
        '<div class="profile-actions"><button class="primary-button" type="submit">Enregistrer</button></div>',
        '</form></section>',
        '<section class="profile-card" aria-labelledby="stats-title">',
        '<h2 id="stats-title">Mon écoute</h2>',
        (f'<dl class="stats-grid">'
         f'<div><dt>Temps écouté estimé</dt><dd>{_duration_text(float(stats.get("estimated_listened_seconds") or 0))}</dd></div>'
         f'<div><dt>Livres terminés</dt><dd>{int(stats.get("completed") or 0)}</dd></div>'
         f'<div><dt>Favoris</dt><dd>{int(stats.get("favorites") or 0)}</dd></div>'
         f'<div><dt>Marque-pages</dt><dd>{int(stats.get("bookmarks") or 0)}</dd></div>'
         '</dl>'
         + (f'<p class="fine">Auteurs les plus écoutés : '
            + ", ".join(ESC(a["name"]) for a in stats.get("top_authors") or []) + '.</p>'
            if stats.get("top_authors") else '')
         + (f'<p class="fine">Séries en cours : '
            + ", ".join(ESC(s["title"]) for s in stats.get("series_in_progress") or []) + '.</p>'
            if stats.get("series_in_progress") else '')
         + '<p class="fine">Estimation calculée à partir des dernières positions enregistrées.</p>'
         if stats else ''),
        '</section>',
        '<section class="profile-card" aria-labelledby="playlists-title">',
        '<h2 id="playlists-title">Mes listes privées</h2>',
        '<p>Rangez vos livres dans vos propres listes. Elles ne sont visibles que par vous.</p>',
        '<ul class="playlist-list">',
        "".join(
            '<li><span>' + ESC(p.get("name") or "Sans titre") + '</span>'
            f'<small>{int(p.get("item_count") or 0)} livre(s)</small>'
            '<form method="post" action="/api/public/playlists/'
            + ESC(p["id"]) + '/delete">'
            f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">'
            '<button class="text-button" type="submit" aria-label="Supprimer la liste">Supprimer</button>'
            '</form></li>'
            for p in (playlists or [])
        ),
        '</ul>' if playlists else '<p class="fine">Aucune liste pour le moment.</p>',
        '<form class="profile-form" method="post" action="/api/public/playlists/create">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<div class="profile-field"><label for="playlist-name">Nouvelle liste</label>',
        '<input id="playlist-name" name="name" type="text" maxlength="80" required '
        'placeholder="Ex. : À écouter en voyage"></div>',
        '<div class="profile-actions"><button class="primary-button" type="submit">Créer la liste</button></div>',
        '</form></section>',
        '<section class="profile-card danger-card" aria-labelledby="profile-delete-title">',
        '<h2 id="profile-delete-title">Supprimer mon compte</h2>',
        '<p>Cette action supprime votre compte public, vos sessions et votre progression d’écoute sur ce portail. Cette action est irréversible.</p>',
        '<form class="profile-form" method="post" action="/profil/supprimer" ',
        'data-confirm="Supprimer définitivement votre compte et votre progression ?">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<div class="profile-actions"><button class="danger-button" type="submit">Supprimer mon compte</button></div>',
        '</form></section>',
        '</main></body></html>',
    ])


def _duration_text(seconds) -> str:
    if not seconds:
        return "Livre audio"
    total = int(float(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s" if secs else f"{minutes} min"
    return f"{secs} s"


def cover_hue(label: str) -> int:
    """Stable colour for a book with no artwork."""
    return sum(ord(c) for c in str(label or "")) * 37 % 360


def fallback_cover_inner(label: str, author: str = "") -> str:
    """Typographic placeholder shown until/unless the real cover loads."""
    title = str(label or "").strip() or "Livre"
    byline = str(author or "").strip()
    return "".join([
        '<span class="cover-fallback" aria-hidden="true">',
        f'<span class="cover-monogram">{ESC(title[:1].upper())}</span>',
        '<span class="cover-copy">',
        '<span class="cover-kicker">Livre audio</span>',
        f'<span class="cover-title">{ESC(title)}</span>',
        f'<span class="cover-author">{ESC(byline or "AURA")}</span>',
        '</span></span>',
    ])


def _position_text(seconds) -> str:
    if not seconds:
        return "0:00"
    total = int(float(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


SORTS = (("Ordre de la collection", ""), ("Titre A→Z", "titre"), ("Auteur A→Z", "auteur"),
         ("Plus récents", "recent"), ("Plus courts", "duree"))


def fold(text) -> str:
    """Lower-case without accents: « Éléonore » matches « eleonore »."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def sort_items(items: list, sort: str) -> list:
    """Order books for the ``tri`` option; unknown values keep the collection order."""
    if sort == "titre":
        return sorted(items, key=lambda i: fold(i.get("title") or i.get("display_name")))
    if sort == "auteur":
        return sorted(items, key=lambda i: (not i.get("author"), fold(i.get("author")),
                                            fold(i.get("title") or i.get("display_name"))))
    if sort == "recent":
        return sorted(items, key=lambda i: int(i.get("created_at") or 0), reverse=True)
    if sort == "duree":
        return sorted(items, key=lambda i: (not i.get("duration_seconds"),
                                            float(i.get("duration_seconds") or 0)))
    return items


def recommend(items: list, limit: int = 8) -> list:
    """Unheard books by the authors the visitor favours or already listens to.

    Signals are the visitor's own favourites (weight 3) and books they started
    (weight 1). No other visitor's data is used. Empty when there is no signal.
    """
    weight: dict = {}
    for item in items:
        author = item.get("author")
        if not author:
            continue
        weight[author] = weight.get(author, 0) \
            + (3 if item.get("favorite") else 0) + (1 if float(item.get("progress_seconds") or 0) > 0 else 0)
    picks = [
        i for i in items
        if i.get("author") and weight.get(i["author"], 0) > 0
        and not i.get("favorite") and not float(i.get("progress_seconds") or 0) > 0
    ]
    picks.sort(key=lambda i: -weight[i["author"]])
    seen, unique = set(), []
    for item in picks:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return unique[:limit]


def _heart_button(item: dict, label: bool = False) -> str:
    """Favourite toggle (needs favorites.js and the CSRF token of #player-bar / body)."""
    on = bool(item.get("favorite"))
    title = str(item.get("title") or item.get("display_name") or "Livre")
    text = ("Dans mes favoris" if on else "Ajouter aux favoris") if label else ""
    return (
        f'<button type="button" class="fav-button{" fav-labeled" if label else ""}" '
        f'data-favorite="{ESC(item.get("id") or "")}" aria-pressed="{"true" if on else "false"}" '
        f'aria-label="Favori : {ESC(title)}" title="Favori">'
        f'<span aria-hidden="true" class="fav-icon">{"♥" if on else "♡"}</span>'
        f'{f"<span class=fav-text>{ESC(text)}</span>" if label else ""}</button>'
    )


def _track_html(item: dict) -> str:
    label = str(item.get("title") or item.get("display_name") or "Livre")
    author = str(item.get("author") or "")
    hue = cover_hue(label)
    duration = float(item.get("duration_seconds") or 0)
    progress = float(item.get("progress_seconds") or 0)
    pct = min(100.0, progress / duration * 100) if duration else 0.0
    cover = item.get("cover_url") or ""
    cover_inner = fallback_cover_inner(label, author)
    if cover:
        cover_inner += f'<img src="{ESC(cover)}" alt="" loading="lazy" data-fallback>'
    stream_url = str(item.get("url") or "")
    download_url = "/d/" + stream_url[3:] if stream_url.startswith("/m/") else ""
    return "".join([
        '<li><button type="button" class="track-button"',
        f' data-url="{ESC(stream_url)}"',
        # The offline button fetches /d/ (premium) but caches it under the
        # streaming /m/ path so the player can serve it while offline.
        f' data-download="{ESC(download_url)}"',
        # Only advertise WebVTT when the catalogue links an actual subtitle
        # object; otherwise every audio track would request a missing .vtt file.
        f' data-subtitle="{ESC(item.get("subtitle_url") or "")}"',
        f' data-object-id="{ESC(item.get("id") or "")}"',
        f' data-title="{ESC(label)}"',
        f' data-author="{ESC(author)}"',
        f' data-cover="{ESC(cover)}"',
        f' data-duration="{duration:.0f}"',
        f' data-progress="{progress:.0f}"',
        f' style="--cover-h:{hue}" aria-label="Écouter {ESC(label)}">',
        f'<span class="cover" aria-hidden="true">{cover_inner}</span>',
        '<span class="track-copy">',
        f'<span class="track-title">{ESC(label)}</span>',
        f'<span class="track-author">{ESC(author or "Livre audio")}</span>',
        (f'<span class="reco-why">{ESC(_REASON_LABELS.get(str((item.get("reco_reasons") or [""])[0]), ""))}</span>'
         if item.get("reco_reasons") else ''),
        f'<span class="track-progress"><i style="width:{pct:.1f}%"></i></span>',
        '</span>',
        f'<span class="track-duration">{ESC(_duration_text(duration))}</span>',
        '</button>',
        _heart_button(item),
        '</li>',
    ])


def catalog_page(
    principal: dict,
    collections: list[dict],
    query: str = "",
    view: str = "liste",
    authors: list[str] | None = None,
    active_author: str = "",
    sort: str = "",
    premium: bool = False,
    page: int = 1,
    page_size: int = 60,
    recommend_fn=None,
    search_note: str = "",
) -> str:
    authors = authors or []
    name = (
        principal.get("display_name")
        or principal.get("email")
        or principal.get("name")
        or "Auditeur"
    )
    csrf = str(principal.get("csrf") or "")
    # Offline download is a premium feature. Free listeners still get the
    # player and the one-minute excerpt; they simply never see the button and
    # cannot obtain the full-file URL from the page.
    offline_button = (
        '<button type="button" class="pill-button icon-button" id="offline-toggle" '
        'aria-pressed="false" title="Télécharger ce livre pour l’écouter sans connexion" '
        'disabled>Télécharger</button>'
        if premium else
        '<span class="premium-hint" title="Réservé aux comptes premium">Premium</span>'
    )

    def href(**changes):
        params = {}
        if query:
            params["q"] = query
        if view != "liste":
            params["vue"] = view
        if active_author:
            params["auteur"] = active_author
        if sort:
            params["tri"] = sort
        if page > 1:
            params["page"] = str(page)
        for key, value in changes.items():
            if value in (None, ""):
                params.pop(key, None)
            else:
                params[key] = value
        return "/?" + urlencode(params) if params else "/"

    all_items = [item for col in collections for item in col.get("items", [])]
    # Paginate the browse list only. The shelves below keep the whole catalogue
    # (they are small, personalised selections) so navigation does not change.
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    start, end = (page - 1) * page_size, page * page_size
    cursor = 0
    visible_collections = []
    for col in collections:
        items = col.get("items", [])
        chunk = items[max(0, start - cursor):max(0, end - cursor)]
        cursor += len(items)
        if chunk:
            visible_collections.append({**col, "items": chunk})
    has_prev = page > 1
    has_next = end < len(all_items)
    seen: set[str] = set()
    resume = []
    for item in sorted(all_items, key=lambda i: float(i.get("progress_seconds") or 0), reverse=True):
        if float(item.get("progress_seconds") or 0) > 0 and item.get("id") not in seen:
            resume.append(item)
            seen.add(item.get("id"))
        if len(resume) >= 8:
            break
    newest = []
    for item in sorted(all_items, key=lambda i: int(i.get("created_at") or 0), reverse=True):
        if item.get("id") not in seen:
            newest.append(item)
            seen.add(item.get("id"))
        if len(newest) >= 8:
            break
    discover = [item for item in all_items[::7] if item.get("id") not in seen][:8]
    favorites = [item for item in all_items if item.get("favorite")]
    # Injected by the API so this module stays independent of the audiobook
    # engine; falls back to the local author-based recommender by default.
    suggested = (recommend_fn or recommend)(all_items)

    id_to_index = {str(item.get("id")): i for i, item in enumerate(all_items)}
    featured = resume[0] if resume else (all_items[0] if all_items else None)
    featured_idx = id_to_index.get(str(featured.get("id"))) if featured else -1

    from collections import Counter
    author_counts = Counter(
        str(item.get("author") or "").strip()
        for item in all_items
        if str(item.get("author") or "").strip()
    )
    author_options = sorted(author_counts.keys(), key=lambda a: a.lower())
    collection_options = [
        {"title": col.get("title") or "Bibliothèque", "count": len(col.get("items", []))}
        for col in collections
    ]

    parts = [
        _HEAD,
        _title("AURA — Bibliothèque"),
        '<header class="topbar"><div class="brand">', _BRAND,
        '<span class="word">AURA</span></div><div class="member">',
        f'<span class="member-name">{ESC(name)}</span>',
        '<a class="text-button" href="/profil">Mon profil</a>',
        '<form method="post" action="/api/public/logout">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<button class="text-button" type="submit">Déconnexion</button>',
        '</form></div></header>',
        f'<main class="library view-{ESC(view)}" id="main">',
        '<header class="library-header"><h1>Bon retour.</h1>',
        '<p class="lede">Reprenez là où votre esprit s\'est arrêté.</p>',
        '<form class="search-form" method="get" action="/">',
        f'<input type="search" name="q" value="{ESC(query)}" '
        'placeholder="Rechercher un livre, un auteur…" aria-label="Rechercher un livre, un auteur">',
        '<button type="submit">Rechercher</button></form>',
    ]
    if search_note:
        parts.append(f'<p class="search-note" role="status">Compris comme : {ESC(search_note)}</p>')
    filters_active = (view != "liste") or bool(active_author) or bool(sort)
    filter_count = (1 if view != "liste" else 0) + (1 if active_author else 0) + (1 if sort else 0)
    if active_author or query:
        parts.append(
            f'<p class="filters-reset"><a class="facet-clear" href="{ESC(href(auteur=None, q=None))}">'
            'Effacer les filtres</a></p>'
        )
    badge = f' <span class="filters-badge">{filter_count}</span>' if filter_count else ""
    parts.append(
        f'<details class="filters-fold" id="filters-fold"{" open" if filters_active else ""}>'
        f'<summary>Affichage et filtres{badge}</summary>'
    )
    parts.append('<div class="controls-block">')
    parts.append('<nav class="control-row" aria-label="Mode d\'affichage"><span class="label">Vue</span>')
    for label, value in (("Liste", "liste"), ("Grille", "grille"), ("Immersif", "immersif")):
        # aria-current must be absent when false, not "false".
        current = ' aria-current="true"' if view == value else ""
        parts.append(
            f'<a class="view-link" href="{ESC(href(vue=value if value != "liste" else None))}"'
            f'{current}>{label}</a>'
        )
    parts.append('</nav>')
    parts.append('<nav class="control-row" aria-label="Tri"><span class="label">Tri</span>')
    for label, value in SORTS:
        current = ' aria-current="true"' if sort == value else ""
        parts.append(
            f'<a class="view-link" href="{ESC(href(tri=value or None))}"{current}>{label}</a>'
        )
    parts.append('</nav>')

    # Collections: only worth a row when there is something to choose between.
    if len(collection_options) > 1:
        parts.append('<nav class="control-row" aria-label="Collections"><span class="label">Collections</span>')
        for copt in collection_options:
            parts.append(
                f'<span class="pill pill-static" title="{ESC(copt["title"])}">'
                f'{ESC(copt["title"])} <small>({copt["count"]})</small></span>'
            )
        parts.append('</nav>')

    # Authors: one select (a long library has dozens), sent as a plain GET form.
    if author_options:
        parts.append(
            '<form class="control-row author-form" method="get" action="/" aria-label="Filtrer par auteur">'
            '<label class="label" for="author-select">Auteur</label>'
        )
        if query:
            parts.append(f'<input type="hidden" name="q" value="{ESC(query)}">')
        if view != "liste":
            parts.append(f'<input type="hidden" name="vue" value="{ESC(view)}">')
        parts.append('<select id="author-select" name="auteur">')
        parts.append(
            f'<option value=""{"" if active_author else " selected"}>'
            f'Tous les auteurs ({len(all_items)})</option>'
        )
        for author in author_options:
            count = author_counts.get(author, 0)
            chosen = " selected" if active_author == author else ""
            parts.append(
                f'<option value="{ESC(author)}"{chosen}>{ESC(author)} ({count})</option>'
            )
        parts.append('</select>')
        parts.append('<noscript><button type="submit" class="text-button">Filtrer</button></noscript>')
        parts.append('</form>')

    parts.append('</div></details>')

    parts.append('</header>')

    # The first book in progress is the resume card itself: the shelf lists the others.
    resume_shelf = resume[1:] if resume else []
    discovery_links = []
    if resume:
        discovery_links.append(("#resume" if resume_shelf else "#resume-card", "Reprendre l'écoute"))
    if favorites:
        discovery_links.append(("#favoris", "Mes favoris"))
    if suggested:
        discovery_links.append(("#pour-vous", "Pour vous"))
    if newest:
        discovery_links.append(("#nouveautes", "Nouveautés"))
    if discover:
        discovery_links.append(("#decouvrir", "À découvrir"))
    if all_items:
        discovery_links.append(("#tous", "Toute la bibliothèque"))
    if len(discovery_links) > 1:
        parts.append(
            '<nav class="discovery" aria-label="Découvrir la bibliothèque">'
            + "".join(f'<a href="{href_}">{ESC(label_)}</a>' for href_, label_ in discovery_links)
            + '</nav>'
        )

    if not all_items:
        parts.extend([
            '<section class="empty-state" aria-live="polite">',
            '<p class="eyebrow">Bibliothèque</p>',
            '<h2>Aucun livre à afficher</h2>',
            '<p>Essayez d’élargir votre recherche, de retirer un filtre ou de revenir à toute la bibliothèque.</p>',
            f'<p><a class="facet-clear" href="{ESC(href(auteur=None, q=None, vue=None))}">Réinitialiser la vue</a></p>',
            '</section>',
        ])

    # Prominent continue card for resumed listening (non-immersive view focus)
    if featured and view != "immersif":
        flabel = str(featured.get("title") or featured.get("display_name") or "Livre")
        fauthor = str(featured.get("author") or "Livre audio")
        fprogress = float(featured.get("progress_seconds") or 0)
        fduration = float(featured.get("duration_seconds") or 0)
        fpct = min(100.0, (fprogress / fduration * 100) if fduration else 0.0)
        fhue = cover_hue(flabel)
        fcover = featured.get("cover_url") or ""
        fcover_inner = fallback_cover_inner(flabel, featured.get("author") or "")
        if fcover:
            fcover_inner += f'<img src="{ESC(fcover)}" alt="" data-fallback>'
        fmeta = "Prêt à être écouté"
        if fprogress and fduration:
            remaining = max(0.0, fduration - fprogress)
            fmeta = f"{_position_text(fprogress)} écouté · {_position_text(remaining)} restant"
        elif fprogress:
            fmeta = f"Repris à {_position_text(fprogress)}"
        elif fduration:
            fmeta = _duration_text(fduration)
        cta = "Continuer l'écoute" if fprogress > 0 else "Lancer l'écoute"
        feyebrow = "Reprendre l'écoute" if fprogress > 0 else "Pour commencer"
        parts.extend([
            '<section class="resume-card" id="resume-card" aria-label="Reprendre l\'écoute">',
            f'<div class="resume-cover" style="--cover-h:{fhue}">{fcover_inner}</div>',
            f'<div class="resume-copy"><p class="eyebrow">{ESC(feyebrow)}</p>',
            f'<h2>{ESC(flabel)}</h2><p>{ESC(fauthor)}</p>',
            f'<p class="resume-meta">{ESC(fmeta)}</p>',
            f'<div class="resume-progress" aria-hidden="true"><i style="width:{fpct:.1f}%"></i></div>',
            '</div><div class="resume-actions">',
            f'<button type="button" class="primary-button" id="resume-continue" data-track-index="{featured_idx}">{cta}</button>',
            '</div></section>',
        ])

    # Immersive hero
    if view == "immersif" and all_items:
        first = featured or all_items[0]
        cover = first.get("cover_url") or ""
        label = str(first.get("title") or first.get("display_name") or "Livre")
        author = str(first.get("author") or "Livre audio")
        hue = cover_hue(label)
        cover_inner = fallback_cover_inner(label, first.get("author") or "")
        img = f'<img src="{ESC(cover)}" alt="" data-fallback>' if cover else ""
        idx = id_to_index.get(str(first.get("id")), 0)
        parts.extend([
            '<section class="hero" id="resume-card" aria-label="Lecture immersive">',
            f'<div class="big-cover" style="--cover-h:{hue}" id="immersive-cover-host">',
            f'{cover_inner}{img}</div>',
            '<div><p class="eyebrow">Lecture immersive</p>',
            f'<h2>{ESC(label)}</h2>',
            f'<p>{ESC(author)}</p>',
            f'<button type="button" class="launch" id="launch" data-track-index="{idx}">Lancer l\'écoute</button>',
            '</div></section>',
        ])

    def shelf(anchor: str, title: str, items: list[dict], desc: str = ""):
        if not items:
            return
        parts.append(f'<section class="shelf" id="{anchor}"><div class="shelf-head">')
        parts.append(f'<h2>{ESC(title)}</h2>')
        if desc:
            parts.append(f'<p class="desc">{ESC(desc)}</p>')
        parts.append('</div><ul>')
        for item in items:
            parts.append(_track_html(item))
        parts.append('</ul></section>')

    shelf("resume", "Reprendre l'écoute", resume_shelf, "Vos autres lectures en cours, à la dernière position.")
    shelf("favoris", "Mes favoris", favorites, "Les livres que vous avez marqués d'un cœur.")
    shelf("pour-vous", "Pour vous", suggested, "Dans la veine de vos favoris et de vos écoutes.")
    shelf("nouveautes", "Nouveautés", newest, "Les titres récemment ajoutés à votre bibliothèque.")
    shelf("decouvrir", "À découvrir", discover, "Une sélection pour varier vos prochaines écoutes.")
    for col in visible_collections:
        shelf("tous", col.get("title") or "Bibliothèque", col.get("items", []))

    if has_prev or has_next:
        parts.append('<nav class="catalog-pages" aria-label="Pages du catalogue">')
        if has_prev:
            parts.append(f'<a class="pill-button" href="{ESC(href(page=page - 1))}" rel="prev">← Précédent</a>')
        parts.append(f'<span class="page-label">Page {page}</span>')
        if has_next:
            parts.append(f'<a class="pill-button" href="{ESC(href(page=page + 1))}" rel="next">Suivant →</a>')
        parts.append('</nav>')

    # Only embed chapters for items that actually appear on this page or in a
    # shelf: a 500-title catalogue no longer ships 500 chapter lists in HTML.
    rendered = resume + favorites + suggested + newest + discover
    rendered += [i for col in visible_collections for i in col.get("items", [])]
    chapter_map = {
        str(item.get("id")): (item.get("chapters") or [])
        for item in rendered
    }
    chapters_json = json.dumps(chapter_map, ensure_ascii=False).replace("<", "\\u003c")
    parts.append(
        '<script type="application/json" id="chapters-data">' + chapters_json + '</script>'
    )

    parts.extend([
        '<audio id="player" preload="metadata" x-webkit-airplay="allow"></audio>',
        f'<section class="player-bar" id="player-bar" data-csrf="{ESC(csrf)}" hidden aria-label="Lecteur audio">',
        '<div class="player-now">',
        '<button type="button" class="player-now-btn" id="player-now-button" aria-label="Ouvrir le lecteur">',
        '<div class="player-cover" id="player-cover" aria-hidden="true"></div>',
        '<div class="now-text">',
        '<p class="now-title" id="now-title" aria-live="polite"></p>',
        '<p class="now-author" id="now-author"></p>',
        '<p class="now-author" id="now-chapter"></p>',
        '</div></button></div>',

        '<div class="player-center">',
        '<div class="transport" role="group" aria-label="Commandes de lecture">',
        '<button type="button" class="icon-button skip" id="prev" aria-label="Titre précédent" title="Titre précédent"><span aria-hidden="true">⏮</span></button>',
        '<button type="button" class="icon-button skip" id="prev-chapter" aria-label="Chapitre précédent" title="Chapitre précédent"><span aria-hidden="true">«</span></button>',
        '<button type="button" class="icon-button skip" id="back15" aria-label="Reculer de 15 secondes" title="Reculer de 15 secondes"><span aria-hidden="true">−15s</span></button>',
        '<button type="button" class="icon-button main" id="play-toggle" aria-label="Lire" title="Lecture / pause"><span aria-hidden="true">▶</span></button>',
        '<button type="button" class="icon-button skip" id="fwd15" aria-label="Avancer de 15 secondes" title="Avancer de 15 secondes"><span aria-hidden="true">+15s</span></button>',
        '<button type="button" class="icon-button skip" id="next-chapter" aria-label="Chapitre suivant" title="Chapitre suivant"><span aria-hidden="true">»</span></button>',
        '<button type="button" class="icon-button skip" id="next" aria-label="Titre suivant" title="Titre suivant"><span aria-hidden="true">⏭</span></button>',
        '</div>',
        '<div class="seek-row">',
        '<span class="time start" id="time-now">0:00</span>',
        '<input class="seek" id="seek" type="range" min="0" max="100" value="0" step="0.1" aria-label="Position dans le livre" aria-valuetext="0:00">',
        '<button type="button" class="time end time-toggle" id="time-total" aria-label="Afficher le temps restant" title="Afficher le temps restant">0:00</button>',
        '</div></div>',

        '<div class="player-actions" aria-label="Options de lecture">',
        '<div class="control-group"><label for="speed">Vitesse</label>',
        '<select id="speed" aria-label="Vitesse de lecture">',
        '<option value="0.5">0,5×</option><option value="0.75">0,75×</option>',
        '<option value="1" selected>1×</option><option value="1.25">1,25×</option>',
        '<option value="1.5">1,5×</option><option value="1.75">1,75×</option>',
        '<option value="2">2×</option><option value="2.5">2,5×</option>',
        '<option value="3">3×</option></select></div>',
        '<div class="control-group"><label for="sleep">Sommeil</label>',
        '<select id="sleep" aria-label="Minuteur de sommeil">',
        '<option value="0">Off</option><option value="5">5 min</option>',
        '<option value="10">10 min</option><option value="15">15 min</option>',
        '<option value="30">30 min</option><option value="45">45 min</option>',
        '<option value="60">60 min</option><option value="chapter">Fin du chapitre</option>',
        '<option value="custom">Personnalisé…</option></select></div>',
        '<div class="control-group"><label for="volume">Volume</label>',
        '<input id="volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volume" aria-valuetext="100 %"></div>',
        '<div class="utility-buttons" role="group" aria-label="Panneaux et affichage">',
        '<button type="button" class="pill-button icon-button" id="chapters-toggle" aria-label="Chapitres" aria-controls="chapters-panel" aria-expanded="false" title="Chapitres">Chapitres</button>',
        '<button type="button" class="pill-button icon-button" id="queue-toggle" aria-label="File d’attente" aria-controls="queue-panel" aria-expanded="false" title="File d’attente">File</button>',
        '<button type="button" class="pill-button icon-button" id="fullscreen" aria-label="Agrandir le lecteur" aria-pressed="false" title="Agrandir le lecteur">Agrandir</button>',
        offline_button,
        '<button type="button" class="pill-button icon-button" id="close" aria-label="Fermer le lecteur" title="Fermer ou arrêter">Fermer</button>',
        '</div></div>',
        '<p class="player-status" id="player-status" role="status" aria-live="polite"></p>',
        '</section>',
        # Native dialogs give focus trapping and Escape for free: no more
        # window.prompt() in the sleep timer or the bookmark note (issue #297).
        '<dialog id="sleep-dialog" aria-labelledby="sleep-dialog-title">',
        '<form method="dialog">',
        '<h3 id="sleep-dialog-title">Minuteur personnalisé</h3>',
        '<label for="sleep-minutes">Durée en minutes</label>',
        '<input id="sleep-minutes" type="number" min="1" max="600" value="20" inputmode="numeric">',
        '<div class="dialog-actions">',
        '<button type="submit" value="cancel">Annuler</button>',
        '<button type="submit" value="confirm" class="primary-button">Démarrer</button>',
        '</div></form></dialog>',
        '<dialog id="note-dialog" aria-labelledby="note-dialog-title">',
        '<form method="dialog">',
        '<h3 id="note-dialog-title">Note du marque-page</h3>',
        '<label for="note-text">Note (facultatif)</label>',
        '<textarea id="note-text" maxlength="200" rows="3"></textarea>',
        '<div class="dialog-actions">',
        '<button type="submit" value="cancel">Annuler</button>',
        '<button type="submit" value="confirm" class="primary-button">Enregistrer</button>',
        '</div></form></dialog>',

        '<aside class="queue-panel" id="queue-panel" hidden aria-label="File d\'attente">',
        '<div class="queue-panel-head"><h3>Dans la file</h3>'
        '<button type="button" class="icon-button panel-close" data-close-panel="queue-panel" aria-label="Fermer la file" title="Fermer">×</button></div>'
        '<div id="queue-list" class="panel-list"></div></aside>',
        '<aside class="queue-panel" id="chapters-panel" hidden aria-label="Chapitres">',
        '<div class="queue-panel-head"><h3>Chapitres</h3>'
        '<button type="button" class="icon-button panel-close" data-close-panel="chapters-panel" aria-label="Fermer les chapitres" title="Fermer">×</button></div>'
        '<div id="chapters-list" class="panel-list"></div>'
        '<div class="bookmarks" id="bookmarks"><div class="bookmarks-head"><h4>Marque-pages</h4>'
        '<button type="button" class="pill-button" id="bookmark-add" disabled>+ Ici</button></div>'
        '<div id="bookmarks-list" class="panel-list"></div></div></aside>',
        '<p class="sync-prompt" id="sync-prompt" role="status" hidden>'
        '<span id="sync-text"></span> <button type="button" class="text-button" id="sync-go">Reprendre</button></p>',

        '<script src="' + asset_url("player.js") + '"></script>',
        '<script src="' + asset_url("shelf.js") + '"></script>',
        '<script src="' + asset_url("favorites.js") + '"></script>',
        '<script src="' + asset_url("offline.js") + '"></script>',
        '<script src="' + asset_url("bookmarks.js") + '"></script>',
        '</main></body></html>',
    ])
    return "".join(parts)
