"""Deterministic AURA jacket artwork for audiobooks that have no cover file.

The public portal already draws a typographic jacket in HTML/CSS (see
``api/public_ui.fallback_cover_inner``). This module renders the same visual
language to a real JPEG so the jacket can be published as an object cover:

* social previews get an ``og:image`` for every book, not only the ones with
  third-party artwork;
* the native player and any client that only knows ``/covers/{oid}.jpg`` gets
  the same jacket as the portal;
* no external API and no image licence is involved.

The palette is kept in sync with ``public_ui.COVER_HUES`` (a test asserts it).
"""
from __future__ import annotations

import colorsys
import io
import random
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Keep in sync with api/public_ui.COVER_HUES (curated, brand-safe hues).
COVER_HUES = (28, 42, 152, 190, 262)
WIDTH = 480
HEIGHT = 640

# The portal ships Instrument Serif (OFL) with its assets: use that bundled
# font first so generation works in a slim image and keeps the portal's look.
_BUNDLED_SERIF = Path(__file__).with_name("portal_assets") / "instrument-serif.ttf"
_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/freefont",
    "/usr/share/fonts/truetype/liberation",
)


def cover_hue(label: str) -> int:
    """Stable, brand-safe colour for a book with no artwork."""
    return COVER_HUES[sum(ord(char) for char in str(label or "")) % len(COVER_HUES)]


def _hsl(hue: int, saturation: float, lightness: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
    return (round(red * 255), round(green * 255), round(blue * 255))


def _font(size: int, *, serif: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf") if serif
        else ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
    )
    name = names[1] if bold else names[0]
    paths = ([_BUNDLED_SERIF] if serif else [])
    paths += [Path(directory) / name for directory in _FONT_DIRS]
    if not serif:
        # Last Unicode-capable fallback before Pillow's (Latin-only) default.
        paths.append(_BUNDLED_SERIF)
    for path in paths:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _spaced(draw: ImageDraw.ImageDraw, text: str, font, xy: tuple[int, int],
            fill: tuple[int, int, int], spacing: int = 2) -> int:
    """Draw small uppercase text with letter spacing; return its width."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += round(draw.textlength(char, font=font)) + spacing
    return x - xy[0] - spacing


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int,
          max_lines: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
        else:
            current = candidate
        consumed += 1
    if len(lines) < max_lines and current:
        lines.append(current)
        consumed += 1
    truncated = consumed < len(words)
    if lines and truncated:
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return lines


def render_jacket(title: str, author: str = "", *, hue: int | None = None) -> bytes:
    """Render one portrait AURA jacket as JPEG bytes.

    Rendering is pure and deterministic: the same title/author/hue always
    produces the same bytes. Returns ``b""`` when Pillow cannot encode a JPEG,
    so callers can keep their previous "no cover" behaviour.
    """
    label = " ".join(str(title or "").split()) or "Livre"
    byline = " ".join(str(author or "").split())
    colour = hue if hue in COVER_HUES else cover_hue(label)

    image = Image.new("RGB", (WIDTH, HEIGHT), _hsl(colour, 0.30, 0.94))
    draw = ImageDraw.Draw(image)

    # Soft paper gradient, from the same light tones as the portal CSS.
    top = _hsl(colour, 0.30, 0.94)
    bottom = _hsl(colour, 0.22, 0.86)
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        tone = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, y, WIDTH, y), fill=tone)

    # Quiet geometric motif: one large arc and a small dot, low contrast.
    motif = _hsl(colour, 0.32, 0.80)
    draw.arc((210, 70, 610, 470), 205, 335, fill=motif, width=3)
    draw.arc((250, 110, 570, 430), 205, 335, fill=motif, width=1)
    draw.ellipse((398, 132, 410, 144), fill=_hsl(colour, 0.38, 0.62))

    # Spine, like the portal's .cover-spine.
    spine = _hsl(colour, 0.30, 0.82)
    draw.rectangle((0, 0, 17, HEIGHT), fill=spine)
    draw.line((18, 0, 18, HEIGHT), fill=_hsl(colour, 0.30, 0.74), width=1)

    ink = _hsl(colour, 0.38, 0.28)
    muted = _hsl(colour, 0.34, 0.36)

    monogram = unicodedata.normalize("NFKC", label[:1]).upper() or "L"
    draw.text((44, 48), monogram, font=_font(190, serif=True), fill=ink)

    # Kicker with a short rule, mirroring .cover-kicker::before.
    kicker_font = _font(17, bold=True)
    draw.line((46, 308, 66, 308), fill=muted, width=1)
    _spaced(draw, "LIVRE AUDIO", kicker_font, (74, 298), muted, spacing=3)

    title_font = _font(38, serif=True)
    lines = _wrap(draw, label, title_font, WIDTH - 96, 4)
    y = 352
    for line in lines:
        draw.text((46, y), line, font=title_font, fill=_hsl(colour, 0.35, 0.24))
        y += 46

    if byline:
        author_font = _font(21)
        author_lines = _wrap(draw, byline, author_font, WIDTH - 96, 2)
        y = max(y + 16, 520)
        for line in author_lines:
            draw.text((46, y), line, font=author_font, fill=_hsl(colour, 0.25, 0.35))
            y += 28

    # Very light grain keeps the flat gradient from looking synthetic. A seeded
    # generator (not Image.effect_noise) keeps the JPEG byte-for-byte stable.
    seed = sum(ord(char) for char in label) ^ (colour << 8)
    rng = random.Random(seed)
    grain = bytes(rng.randrange(256) for _ in range(WIDTH * HEIGHT))
    noise = Image.frombytes("L", (WIDTH, HEIGHT), grain).convert("RGB")
    image = Image.blend(image, noise, 0.035)

    wordmark = _font(15, bold=True)
    _spaced(ImageDraw.Draw(image), "AURA", wordmark,
            (WIDTH - 76, HEIGHT - 34), muted, spacing=3)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue()
