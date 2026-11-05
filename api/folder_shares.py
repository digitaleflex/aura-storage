"""Public folder share links: subtree helpers and the HTML listing page.

A folder share is the same capability model as ``api/shares.py``: one
unauthenticated, expiring, revocable, read-only link. The difference is that it
covers a whole folder tree, so the link cannot answer with a single redirect:
it serves a small no-JavaScript HTML listing and each file it lists redirects to
a short-lived presigned GET. Bytes still never pass through the API.

Security rules kept here:

- names are user-controlled, so every value interpolated into the page is
  HTML-escaped and the page carries a strict CSP;
- the page mirrors ``SAFE_INLINE_TYPES``: active documents are download-only;
- links are relative to the token path, so the page never needs the request
  Host header, and no absolute storage URL is ever rendered.
"""
from html import escape
import time
from typing import Optional

# Mirrors MAX_FOLDER_DEPTH in api/main.py. A subtree walk that goes deeper than
# the cap cannot belong to a folder the application could have created.
MAX_DEPTH = 32

# One page of files. A share link must stay cheap to render even for a large
# folder; the listing links to the next page with an offset.
PAGE_SIZE = 100


def folder_in_subtree(repo, folder_id: Optional[str], root_id: str, owner_id: str) -> bool:
    """True when ``folder_id`` is ``root_id`` or one of its descendants.

    Folders are owner-scoped, so every step is read with the owner filter. A
    missing/foreign folder answers False, which the caller turns into the same
    404 as every other failure mode.
    """
    current = folder_id
    for _ in range(MAX_DEPTH + 1):
        if current is None:
            return False
        if current == root_id:
            return True
        row = repo.get_folder(current, owner_id=owner_id)
        if row is None:
            return False
        current = row["parent_id"]
    return False


def folder_path(
    repo, folder_id: str, root_id: str, owner_id: str
) -> Optional[list[dict]]:
    """Ancestor chain from the shared root down to ``folder_id`` (inclusive).

    Returns None when the folder is outside the shared subtree, so callers keep
    the single "not found" behaviour.
    """
    chain: list[dict] = []
    current: Optional[str] = folder_id
    for _ in range(MAX_DEPTH + 1):
        if current is None:
            return None
        row = repo.get_folder(current, owner_id=owner_id)
        if row is None:
            return None
        chain.append(row)
        if current == root_id:
            chain.reverse()
            return chain
        current = row["parent_id"]
    return None


def format_bytes(size: int) -> str:
    """Human-readable size without a locale dependency (the API runs anywhere)."""
    value = max(0, int(size))
    units = ("o", "Ko", "Mo", "Go", "To")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "o":
                return f"{int(amount)} o"
            return f"{amount:.1f} {unit}".replace(".", ",")
        amount /= 1024
    return f"{value} o"


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _query(base: str, folder_id: Optional[str], page: int) -> str:
    params: list[str] = []
    if folder_id is not None:
        params.append(f"d={_e(folder_id)}")
    if page:
        params.append(f"page={int(page)}")
    return f"{base}?{'&amp;'.join(params)}" if params else base


def _breadcrumb(base: str, chain: list[dict]) -> str:
    crumbs: list[str] = []
    for index, folder in enumerate(chain):
        name = _e(folder["name"])
        if index == len(chain) - 1:
            crumbs.append(f'<li aria-current="page">{name}</li>')
        else:
            href = _query(base, folder["id"], 0)
            crumbs.append(f'<li><a href="{href}">{name}</a></li>')
    return "".join(crumbs)


def _folder_rows(base: str, folders: list[dict]) -> str:
    return "".join(
        f'<li class="row">'
        f'<span class="glyph" aria-hidden="true">▸</span>'
        f'<a class="name" href="{_query(base, folder["id"], 0)}">{_e(folder["name"])}</a>'
        f'<span class="meta">Dossier</span>'
        f"</li>"
        for folder in folders
    )


def _file_rows(base: str, objects: list[dict], inline_allowed) -> str:
    rows: list[str] = []
    for obj in objects:
        oid = _e(obj["id"])
        inline = inline_allowed(obj.get("content_type", ""))
        open_href = f"{base}/o/{oid}" + ("" if inline else "?download=1")
        download_href = f"{base}/o/{oid}?download=1"
        download = (
            '<a class="action" href="%s" rel="nofollow">Télécharger</a>' % download_href
            if inline
            else ""
        )
        rows.append(
            '<li class="row">'
            '<span class="glyph" aria-hidden="true">▤</span>'
            f'<a class="name" href="{open_href}" rel="nofollow">{_e(obj["display_name"])}</a>'
            f'<span class="meta">{_e(format_bytes(int(obj["size_bytes"])))}</span>'
            f"{download}"
            "</li>"
        )
    return "".join(rows)


def render_page(
    *,
    token: str,
    folder: dict,
    chain: list[dict],
    folders: list[dict],
    objects: list[dict],
    page: int,
    has_next: bool,
    expires_at: int,
    inline_allowed,
    now: int,
) -> str:
    """Render the public listing page. Every interpolated value is escaped."""
    base = f"/f/{_e(token)}"
    current = chain[-1] if chain else folder
    title = _e(current["name"])
    root = chain[0] if chain else folder

    crumbs = _breadcrumb(base, chain) if chain else ""
    folder_rows = _folder_rows(base, folders)
    file_rows = _file_rows(base, objects, inline_allowed)
    empty = not folders and not objects
    parent_link = ""
    if len(chain) > 1:
        parent_link = (
            f'<a class="back" href="{_query(base, chain[-2]["id"], 0)}">'
            "↑ Dossier parent</a>"
        )
    next_link = ""
    if has_next:
        next_link = (
            f'<nav class="pager"><a href="{_query(base, current["id"], page + 1)}">'
            "Fichiers suivants →</a></nav>"
        )
    previous_link = ""
    if page > 0:
        previous_link = (
            f'<nav class="pager"><a href="{_query(base, current["id"], page - 1)}">'
            "← Fichiers précédents</a></nav>"
        )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title} — AURA</title>
<style>
:root {{ color-scheme: light dark; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 2rem 1rem; min-height: 100vh;
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: Canvas; color: CanvasText;
}}
main {{ max-width: 46rem; margin: 0 auto; }}
.eyebrow {{
  margin: 0 0 .25rem; font-size: .75rem; letter-spacing: .08em;
  text-transform: uppercase; opacity: .65;
}}
h1 {{ margin: 0 0 1rem; font-size: 1.6rem; line-height: 1.25; overflow-wrap: anywhere; }}
h2 {{ margin: 1.5rem 0 .5rem; font-size: .95rem; text-transform: uppercase; letter-spacing: .05em; opacity: .7; }}
ol {{ list-style: none; display: flex; flex-wrap: wrap; gap: .35rem; margin: 0 0 1rem; padding: 0; font-size: .9rem; }}
ol li + li::before {{ content: "/"; margin-right: .35rem; opacity: .45; }}
a {{ color: LinkText; }}
.back {{ display: inline-block; margin-bottom: 1rem; font-size: .9rem; }}
ul.items {{ list-style: none; margin: 0; padding: 0; border-top: 1px solid color-mix(in srgb, CanvasText 18%, transparent); }}
.row {{ display: flex; align-items: center; gap: .6rem; padding: .55rem .25rem; border-bottom: 1px solid color-mix(in srgb, CanvasText 12%, transparent); }}
.glyph {{ width: 1.1rem; text-align: center; opacity: .55; }}
.name {{ flex: 1 1 auto; overflow-wrap: anywhere; text-decoration: none; }}
.name:hover {{ text-decoration: underline; }}
.meta {{ flex: 0 0 auto; font-size: .8rem; opacity: .65; white-space: nowrap; }}
.action {{ flex: 0 0 auto; font-size: .8rem; }}
.empty {{ margin: 1.5rem 0; opacity: .7; }}
.pager {{ margin: 1rem 0; font-size: .9rem; }}
footer {{ margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid color-mix(in srgb, CanvasText 18%, transparent); font-size: .8rem; opacity: .7; }}
</style>
</head>
<body>
<main>
<header>
<p class="eyebrow">Dossier partagé · AURA</p>
<h1>{title}</h1>
<nav aria-label="Fil d'Ariane"><ol>{crumbs}</ol></nav>
</header>
{parent_link}
{folder_rows and f'<section aria-labelledby="folders-title"><h2 id="folders-title">Dossiers</h2><ul class="items">{folder_rows}</ul></section>' or ""}
{file_rows and f'<section aria-labelledby="files-title"><h2 id="files-title">Fichiers</h2><ul class="items">{file_rows}</ul></section>' or ""}
{empty and '<p class="empty">Ce dossier ne contient aucun fichier.</p>' or ""}
{previous_link}
{next_link}
<footer>
<p>Lien valable jusqu'au {_e(_date(expires_at))}. Il peut être révoqué à tout moment.</p>
<p>Seules les lectures effectuées depuis ce lien sont enregistrées. Aucun compte AURA n'est nécessaire.</p>
</footer>
</main>
</body>
</html>"""


def _date(epoch: int) -> str:
    try:
        return time.strftime("%d/%m/%Y à %H:%M UTC", time.gmtime(int(epoch)))
    except (OverflowError, OSError, ValueError):
        return "—"


def render_not_found() -> str:
    """One indistinguishable page for every failure mode of a folder link."""
    return """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Lien introuvable — AURA</title>
<style>
body {{ margin: 0; padding: 3rem 1rem; font: 16px/1.5 system-ui, sans-serif; text-align: center; background: Canvas; color: CanvasText; }}
h1 {{ font-size: 1.4rem; }}
p {{ opacity: .7; }}
</style>
</head>
<body>
<main>
<h1>Lien introuvable</h1>
<p>Ce lien de partage n'existe pas, a expiré ou a été révoqué.</p>
</main>
</body>
</html>"""
