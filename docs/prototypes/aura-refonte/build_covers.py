#!/usr/bin/env python3
"""Generate original, typographic cover art for the AURA design prototype.

All titles, authors and covers are illustrative mock data. Run:
    python3 build_covers.py
"""
from pathlib import Path

OUT = Path(__file__).with_name("assets") / "covers"
OUT.mkdir(parents=True, exist_ok=True)

BOOKS = [
    ("la-peste", "La Peste", "ALBERT CAMUS", "#20364D", "#F6F0E4", "#CBA96E", "arc"),
    ("petit-prince", "Le Petit\nPrince", "ANTOINE DE SAINT-EXUPÉRY", "#E7D8B6", "#21384F", "#A87636", "circle"),
    ("madame-bovary", "Madame\nBovary", "GUSTAVE FLAUBERT", "#7C4B3E", "#F8F0E3", "#E6C99E", "frame"),
    ("fleurs-du-mal", "Les Fleurs\ndu Mal", "CHARLES BAUDELAIRE", "#2D463B", "#F3EADB", "#C7A96C", "stripes"),
    ("etranger", "L'Étranger", "ALBERT CAMUS", "#ECE4D6", "#1F3046", "#B4764C", "sun"),
    ("temps-retrouve", "Le Temps\nretrouvé", "MARCEL PROUST", "#59546D", "#F6F0E5", "#D9C08D", "waves"),
    ("monte-cristo", "Le Comte de\nMonte-Cristo", "ALEXANDRE DUMAS", "#233C3A", "#F4EBDD", "#D0A56C", "frame"),
    ("miserables", "Les\nMisérables", "VICTOR HUGO", "#393833", "#F5EEDF", "#C69B5F", "stripes"),
    ("de-lamour", "De l'Amour", "STENDHAL", "#E5D2C9", "#4A2F34", "#9C5F42", "circle"),
    ("journal-fou", "Le Journal\nd'un Fou", "GUY DE MAUPASSANT", "#D8D4C7", "#253347", "#8A6A45", "lines"),
    ("contes", "Contes &\nLégendes", "COLLECTIF", "#C8A05C", "#26364A", "#F5EFE2", "stars"),
    ("nature-voyage", "La Nature\nen Voyage", "COLLECTIF", "#6E7A62", "#F6F2E7", "#D7C79C", "hills"),
    ("poemes", "Poèmes\nchoisis", "EMILY DICKINSON", "#ECE7EE", "#39334A", "#8C6E90", "frame"),
    ("sous-soleil", "Sous le soleil\nde Satan", "GEORGES BERNANOS", "#8B4036", "#F8ECDC", "#E8C38F", "sun"),
    ("nouvelles", "Nouvelles\nchoisies", "COLLECTIF", "#DDD6C7", "#263648", "#A97C4E", "grid"),
    ("lettres", "Lettres à\nun jeune poète", "R. M. RILKE", "#273C55", "#F5EFE2", "#C9A36A", "circle"),
]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def motif(kind: str, accent: str) -> str:
    if kind == "arc":
        return (f'<path d="M300 120 A230 230 0 0 1 530 350" fill="none" '
                f'stroke="{accent}" stroke-width="2" opacity=".75"/>'
                f'<path d="M300 160 A190 190 0 0 1 490 350" fill="none" '
                f'stroke="{accent}" stroke-width="1" opacity=".45"/>')
    if kind == "circle":
        return (f'<circle cx="300" cy="338" r="176" fill="none" stroke="{accent}" '
                f'stroke-width="2" opacity=".7"/>'
                f'<circle cx="300" cy="338" r="150" fill="none" stroke="{accent}" '
                f'stroke-width="1" opacity=".35"/>')
    if kind == "frame":
        return (f'<rect x="66" y="66" width="468" height="768" fill="none" '
                f'stroke="{accent}" stroke-width="1.5" opacity=".7"/>'
                f'<rect x="78" y="78" width="444" height="744" fill="none" '
                f'stroke="{accent}" stroke-width=".7" opacity=".35"/>')
    if kind == "stripes":
        return "".join(
            f'<line x1="{x}" y1="72" x2="{x}" y2="828" stroke="{accent}" stroke-width="1" opacity=".28"/>'
            for x in range(96, 520, 26)
        )
    if kind == "sun":
        return (f'<circle cx="300" cy="320" r="128" fill="{accent}" opacity=".85"/>'
                f'<line x1="172" y1="448" x2="428" y2="448" stroke="{accent}" stroke-width="2" opacity=".5"/>')
    if kind == "waves":
        return "".join(
            f'<path d="M40 {330 + i*26} Q170 {300 + i*26} 300 {330 + i*26} T560 {330 + i*26}" '
            f'fill="none" stroke="{accent}" stroke-width="1.2" opacity="{max(.18, .55 - i*.08):.2f}"/>'
            for i in range(6)
        )
    if kind == "lines":
        return "".join(
            f'<line x1="96" y1="{270 + i*22}" x2="{304 + (i%3)*40}" y2="{270 + i*22}" '
            f'stroke="{accent}" stroke-width="1" opacity=".35"/>' for i in range(8)
        )
    if kind == "stars":
        return "".join(
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{accent}" opacity="{o}"/>'
            for x, y, r, o in [
                (104, 148, 3, .8), (470, 196, 2, .6), (150, 700, 2, .5),
                (492, 660, 3, .7), (430, 120, 1.6, .5), (88, 620, 2, .5),
            ]
        )
    if kind == "hills":
        return (f'<path d="M0 520 Q150 410 300 500 T600 480 L600 900 L0 900Z" fill="{accent}" opacity=".22"/>'
                f'<path d="M0 600 Q170 500 320 580 T600 560 L600 900 L0 900Z" fill="{accent}" opacity=".16"/>')
    if kind == "grid":
        return "".join(
            f'<rect x="{x}" y="{y}" width="44" height="44" fill="none" stroke="{accent}" '
            f'stroke-width="1" opacity=".3"/>'
            for x in (110, 220, 330, 440) for y in (150, 250, 620, 720)
        )
    return ""


def title_lines(title: str, size: int = 74) -> str:
    lines = title.split("\n")
    out = []
    for i, line in enumerate(lines):
        y = 384 + i * (size + 10) - (len(lines) - 1) * (size + 10) / 2
        out.append(
            f'<text x="300" y="{y:.0f}" text-anchor="middle" font-family="Georgia, \'Times New Roman\', serif" '
            f'font-size="{size}" fill="currentColor">{esc(line)}</text>'
        )
    return "".join(out)


def build(slug, title, author, bg, fg, accent, kind) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 900" role="img" aria-label="Couverture : {esc(title.replace(chr(10), ' '))}">
  <rect width="600" height="900" fill="{bg}"/>
  <g color="{fg}">{motif(kind, accent)}
    <text x="300" y="104" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" letter-spacing="5" fill="{accent}">AURA</text>
    <text x="300" y="136" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="12" letter-spacing="3" opacity=".62">BIBLIOTHÈQUE AUDIO</text>
    {title_lines(title)}
    <line x1="210" y1="552" x2="390" y2="552" stroke="{accent}" stroke-width="1.5" opacity=".9"/>
    <text x="300" y="596" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="16" letter-spacing="3.5" fill="{fg}" opacity=".9">{esc(author)}</text>
    <text x="300" y="826" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="11" letter-spacing="4" fill="{accent}" opacity=".8">ÉDITIONS AURA</text>
  </g>
</svg>
'''


for book in BOOKS:
    (OUT / f"{book[0]}.svg").write_text(build(*book), encoding="utf-8")

print(f"Generated {len(BOOKS)} covers in {OUT}")
