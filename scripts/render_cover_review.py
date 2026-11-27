#!/usr/bin/env python3
"""Render a self-contained HTML review page for cover candidates.

The page only displays images and exports operator selections. It never calls
the AURA API and cannot publish a cover by itself.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

AUTHOR_STOPWORDS = {"and", "de", "du", "et", "la", "le", "les", "the"}
COVER_HOST_RULES = (
    "covers.openlibrary.org", ".mzstatic.com",
    "books.google.com", ".googleusercontent.com", ".gstatic.com",
)


def reject_constant(value: str):
    raise ValueError(f"valeur JSON non autorisee: {value}")


def allowed_cover_url(url: object) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    return any(host == rule or (rule.startswith(".") and host.endswith(rule))
               for rule in COVER_HOST_RULES)


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().split(":", 1)[0]
    text = re.sub(r"\([^)]*(?:extrait|film|introduction|partie|integrale|unabridged)[^)]*\)",
                  " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def author_key(value: object) -> str:
    return " ".join(word for word in normalize(value).split()
                    if word not in AUTHOR_STOPWORDS)


def match_class(book: dict, candidate: dict) -> str:
    title_exact = normalize(book.get("title")) == normalize(candidate.get("title"))
    if not title_exact:
        return "approx"
    expected = author_key(book.get("author"))
    actual = author_key(candidate.get("author"))
    if not expected or expected == actual:
        return "exact"
    return "title"


MATCH_LABELS = {
    "exact": "Titre + auteur concordants",
    "title": "Titre concordant",
    "approx": "À vérifier",
}


def render(review: dict) -> str:
    if not isinstance(review, dict) or not isinstance(review.get("books"), list):
        raise ValueError("le fichier de revue doit contenir une liste 'books'")
    books = review["books"]
    if any(not isinstance(book, dict) for book in books):
        raise ValueError("entree de livre non objet")
    sections = []
    for number, book in enumerate(books, 1):
        candidates = book.get("candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        cards = []
        for index, candidate in enumerate(candidates):
            url = str(candidate.get("url") or "")
            if not allowed_cover_url(url):
                continue
            match = match_class(book, candidate)
            provider = html.escape(str(candidate.get("provider") or ""))
            title = html.escape(str(candidate.get("title") or "Titre inconnu"))
            author = html.escape(str(candidate.get("author") or ""))
            cards.append(f"""
              <label class="candidate {match}">
                <input type="radio" name="book-{number}" value="{index}" data-match="{match}">
                <img src="{html.escape(url, quote=True)}" alt="Couverture : {title}"
                     loading="lazy" referrerpolicy="no-referrer">
                <span class="candidate-copy">
                  <span class="badges"><span class="provider">{provider}</span>
                    <span class="match">{MATCH_LABELS[match]}</span></span>
                  <strong>{title}</strong><span class="author">{author}</span>
                </span>
              </label>""")
        if not cards:
            cards.append('<p class="empty">Aucun candidat automatique. Ajoutez une image manuellement.</p>')
        title = html.escape(str(book.get("title") or "Titre inconnu"))
        author = html.escape(str(book.get("author") or "Auteur non précisé"))
        display_name = html.escape(str(book.get("display_name") or ""))
        object_id = html.escape(str(book.get("object_id") or ""), quote=True)
        sections.append(f"""
        <section class="book" id="book-{number}">
          <div class="book-heading"><span class="number">{number}</span>
            <div><h2>{title}</h2><p class="byline">{author}</p>
              <p class="object-id">{display_name} · {object_id}</p></div></div>
          <div class="candidates">{''.join(cards)}</div>
          <label class="skip"><input type="radio" name="book-{number}" value="">
            Ne pas appliquer de couverture</label>
        </section>""")

    review_json = json.dumps(review, ensure_ascii=False, allow_nan=False)
    review_json = (review_json.replace("&", "\\u0026").replace("<", "\\u003c")
                   .replace(">", "\\u003e").replace("\u2028", "\\u2028")
                   .replace("\u2029", "\\u2029"))
    total_candidates = sum(
        len(book["candidates"]) for book in books
        if isinstance(book.get("candidates"), list)
    )
    with_candidates = sum(
        isinstance(book.get("candidates"), list) and bool(book["candidates"])
        for book in books
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AURA — Validation des couvertures</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f4f1ea; --panel:#fffdf8; --ink:#20221f;
    --muted:#6c7068; --line:#dcd8ce; --accent:#285c46; --warn:#8a5318; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#171a18; --panel:#202521;
    --ink:#f0f2ed; --muted:#a7afa7; --line:#394039; --accent:#8bc7a7; --warn:#e3b077; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  header {{ position:sticky; top:0; z-index:5; background:var(--panel);
    border-bottom:1px solid var(--line); padding:20px max(20px,calc((100vw - 1180px)/2)); }}
  h1 {{ margin:0 0 4px; font-size:24px; }} header p {{ margin:0; color:var(--muted); }}
  .toolbar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:14px; }}
  button {{ border:1px solid var(--line); border-radius:8px; padding:9px 13px;
    background:var(--panel); color:var(--ink); cursor:pointer; font:inherit; }}
  button.primary {{ background:var(--accent); color:var(--panel); border-color:var(--accent); }}
  button:hover {{ filter:brightness(.96); }} .counter {{ color:var(--muted); margin-left:auto; }}
  main {{ max-width:1180px; margin:auto; padding:24px 20px 60px; }}
  .book {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:20px; margin:0 0 18px; }}
  .book-heading {{ display:flex; gap:12px; align-items:flex-start; margin-bottom:16px; }}
  .number {{ display:grid; place-items:center; min-width:30px; height:30px; border-radius:50%;
    background:var(--bg); color:var(--muted); font-weight:700; }}
  h2 {{ font-size:19px; margin:0; }} .byline {{ margin:2px 0; color:var(--muted); }}
  .object-id {{ margin:0; color:var(--muted); font-size:11px; overflow-wrap:anywhere; }}
  .candidates {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(245px,1fr)); gap:12px; }}
  .candidate {{ position:relative; display:grid; grid-template-columns:96px 1fr; gap:12px;
    border:1px solid var(--line); border-radius:10px; padding:10px; cursor:pointer; min-height:150px; }}
  .candidate:has(input:checked) {{ border:2px solid var(--accent); padding:9px; }}
  .candidate input {{ position:absolute; top:8px; left:8px; width:18px; height:18px; accent-color:var(--accent); }}
  .candidate img {{ width:96px; height:138px; object-fit:contain; background:#e9e6df;
    border-radius:5px; margin-left:22px; }}
  .candidate-copy {{ display:flex; flex-direction:column; gap:5px; min-width:0; }}
  .candidate-copy strong {{ font-size:14px; }} .author {{ color:var(--muted); font-size:13px; }}
  .badges {{ display:flex; flex-wrap:wrap; gap:5px; margin-bottom:3px; }}
  .badge,.provider,.match {{ display:inline-block; border-radius:99px; padding:2px 7px; font-size:10px;
    background:var(--bg); color:var(--muted); }}
  .exact .match {{ color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,transparent); }}
  .title .match {{ color:var(--warn); background:color-mix(in srgb,var(--warn) 12%,transparent); }}
  .skip {{ display:inline-flex; gap:7px; align-items:center; margin-top:14px; color:var(--muted); }}
  .skip input {{ accent-color:var(--accent); }} .empty {{ color:var(--muted); grid-column:1/-1; }}
  footer {{ max-width:1180px; margin:auto; padding:0 20px 40px; color:var(--muted); font-size:13px; }}
  code {{ overflow-wrap:anywhere; }}
  @media (max-width:520px) {{ .counter {{ width:100%; margin-left:0; }} .candidate {{ grid-template-columns:82px 1fr; }}
    .candidate img {{ width:82px; height:122px; }} }}
</style>
</head>
<body>
<header>
  <h1>Validation des couvertures</h1>
  <p>{len(books)} livres · {with_candidates} avec candidats · {total_candidates} propositions.
     Sélectionnez une image par livre, puis exportez vos choix.</p>
  <div class="toolbar">
    <button id="select-exact">Sélectionner les concordances exactes</button>
    <button id="clear">Tout effacer</button>
    <button id="export" class="primary">Exporter les sélections</button>
    <span class="counter" id="counter">0 sélection(s)</span>
  </div>
</header>
<main>{''.join(sections)}</main>
<footer>
  Cette page ne publie rien. Enregistrez le JSON exporté, puis lancez :
  <code>scripts/apply_cover_candidates.sh /chemin/cover-selections.json --dry-run</code>,
  vérifiez le résultat, puis relancez sans <code>--dry-run</code>.
  Les couvertures restent soumises au droit d'auteur ; vérifiez votre droit à les afficher.
</footer>
<script id="review-data" type="application/json">{review_json}</script>
<script>
const review = JSON.parse(document.getElementById('review-data').textContent);
const counter = document.getElementById('counter');
function updateCounter() {{
  counter.textContent = document.querySelectorAll('.candidate input:checked').length + ' sélection(s)';
}}
document.addEventListener('change', updateCounter);
document.getElementById('select-exact').addEventListener('click', () => {{
  document.querySelectorAll('.candidate input[data-match="exact"]').forEach(input => {{
    if (!document.querySelector(`input[name="${{input.name}}"]:checked`)) input.checked = true;
  }});
  updateCounter();
}});
document.getElementById('clear').addEventListener('click', () => {{
  document.querySelectorAll('input[type="radio"]').forEach(input => input.checked = false);
  updateCounter();
}});
document.getElementById('export').addEventListener('click', () => {{
  const books = review.books.map((book, index) => {{
    const input = document.querySelector(`input[name="book-${{index + 1}}"]:checked`);
    const chosen = input && input.value !== '' ? Number(input.value) : null;
    const candidate = chosen === null ? null : (book.candidates || [])[chosen];
    const result = {{...book}};
    delete result.error;
    if (chosen === null || !candidate) {{
      result.status = ['applied', 'already_applied'].includes(book.status) ? book.status : 'pending';
      result.chosen_url = null;
      result.chosen_candidate = null;
    }} else {{
      result.status = 'selected';
      result.chosen_url = candidate.url;
      result.chosen_candidate = chosen;
    }}
    return result;
  }});
  const payload = {{...review, exported_at: Math.floor(Date.now() / 1000), books}};
  const blob = new Blob([JSON.stringify(payload, null, 2) + '\\n'], {{type:'application/json'}});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'cover-selections.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}});
updateCounter();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="?",
        default=(
            os.environ.get("AURA_COVER_REVIEW_FILE")
            or f"{os.environ.get('AURA_DATA_DIR', '/srv/aura-storage')}/cover-review/cover-candidates.json"
        ),
    )
    parser.add_argument("--output", default="/srv/aura-storage/cover-review.html")
    args = parser.parse_args()
    source = Path(args.input)
    review = json.loads(
        source.read_text(encoding="utf-8"), parse_constant=reject_constant,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(review), encoding="utf-8")
    print(f"Page de validation: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
