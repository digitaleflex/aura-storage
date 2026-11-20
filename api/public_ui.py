"""HTML for the public portal.

Deliberately dependency-free: pages are served by the API on the public host,
with no JavaScript bundle and no external font/CDN. The visual direction is a
warm library — cream paper, night-ink text, serif display, one clear action.
"""
import html

ESC = lambda value: html.escape(str(value if value is not None else ""), quote=True)

_CSS = """
:root{
  --paper:#f6f1e7; --paper-deep:#efe6d6; --sheet:#fffdf8;
  --ink:#1b2b3a; --ink-soft:#445264; --muted:#5f5d55;
  --brass:#875f24; --line:rgba(27,43,58,.14);
}
*{box-sizing:border-box}
html{min-height:100%}
body{
  margin:0; min-height:100vh; color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:16px; line-height:1.65;
  background:
    radial-gradient(circle at 12% 8%, rgba(255,255,255,.85) 0, transparent 42%),
    radial-gradient(circle at 88% 92%, rgba(168,122,53,.10) 0, transparent 38%),
    var(--paper);
}
a{color:inherit}
.nowrap{white-space:nowrap}
.serif{font-family:Georgia,"Iowan Old Style","Palatino Linotype",serif}

/* ---- shared brand ---------------------------------------------------- */
.brand{display:inline-flex;align-items:center;gap:.65rem;font-size:.82rem;
  letter-spacing:.22em;font-weight:700;text-transform:uppercase;color:var(--ink)}
.brand svg{width:30px;height:30px;flex:none}
.brand .word{display:inline-block;transform:translateY(.02em)}

/* ---- login ----------------------------------------------------------- */
.stage{
  min-height:100vh; display:grid; gap:clamp(2.5rem,6vw,6rem);
  grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);
  align-items:center; max-width:1120px; margin:0 auto;
  padding:clamp(2rem,6vh,5rem) clamp(1.25rem,5vw,3rem);
}
.intro .kicker{margin:2.6rem 0 .9rem;font-size:.78rem;letter-spacing:.2em;
  text-transform:uppercase;color:var(--brass);font-weight:700}
.intro h1{
  margin:0; font-family:Georgia,"Iowan Old Style","Palatino Linotype",serif;
  font-weight:400; font-size:clamp(2.5rem,5.2vw,4rem); line-height:1.13;
  letter-spacing:-.02em;
}
.intro .lede{max-width:32rem;margin:1.4rem 0 0;color:var(--muted);font-size:1.06rem}
.wave{display:flex;align-items:center;gap:5px;height:34px;margin-top:2.6rem;
  color:var(--brass);opacity:.85}
.wave i{display:block;width:3px;border-radius:3px;background:currentColor}
.wave i:nth-child(1){height:8px}.wave i:nth-child(2){height:18px}
.wave i:nth-child(3){height:30px}.wave i:nth-child(4){height:14px}
.wave i:nth-child(5){height:24px}.wave i:nth-child(6){height:9px}
.wave i:nth-child(7){height:16px}

.access{max-width:26rem;width:100%;justify-self:end}
.panel{
  background:var(--sheet); border:1px solid var(--line);
  border-radius:4px; padding:clamp(1.75rem,3vw,2.5rem);
  box-shadow:0 18px 40px -28px rgba(27,43,58,.45), 0 2px 0 rgba(27,43,58,.04);
}
.eyebrow{margin:0 0 1rem;font-size:.74rem;letter-spacing:.18em;
  text-transform:uppercase;color:var(--brass);font-weight:700}
.panel h2{margin:0;font-family:Georgia,serif;font-weight:400;
  font-size:1.75rem;line-height:1.25;letter-spacing:-.01em}
.hint{margin:.85rem 0 1.9rem;color:var(--muted);font-size:.96rem;line-height:1.6}
.google-button{
  display:flex;align-items:center;justify-content:center;gap:.75rem;
  width:100%;min-height:52px;padding:.7rem 1rem;border-radius:3px;
  background:#fff;border:1px solid rgba(27,43,58,.2);
  box-shadow:0 2px 0 rgba(27,43,58,.10);
  font-size:1rem;font-weight:600;text-decoration:none;color:var(--ink);
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.google-button svg{width:20px;height:20px;flex:none}
.google-button:hover{border-color:rgba(27,43,58,.42);
  box-shadow:0 5px 14px -6px rgba(27,43,58,.35);transform:translateY(-1px)}
.google-button:active{transform:translateY(0);box-shadow:0 1px 0 rgba(27,43,58,.12)}
.google-button:focus-visible,.text-button:focus-visible{
  outline:3px solid var(--brass);outline-offset:3px}
.fine{margin:1.25rem 0 0;font-size:.83rem;color:var(--muted);text-align:center}
.rule{display:flex;align-items:center;gap:.9rem;margin:1.6rem 0 .9rem;
  color:var(--brass)}
.rule span{height:1px;background:var(--line);flex:1}
.rule i{width:5px;height:5px;background:var(--brass);transform:rotate(45deg)}
.foot{margin:0;text-align:center;font-size:.78rem;letter-spacing:.08em;
  color:var(--muted)}

/* ---- catalogue ------------------------------------------------------- */
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:1rem;
  flex-wrap:wrap;max-width:960px;margin:0 auto;
  padding:1.6rem clamp(1.25rem,5vw,2rem) 1rem;
  border-bottom:1px solid var(--line);
}
.member{display:flex;align-items:center;gap:1rem;font-size:.9rem;color:var(--muted)}
.text-button{font:inherit;color:var(--ink);background:none;border:0;
  border-bottom:1px solid var(--brass);padding:0 0 2px;cursor:pointer;
  border-radius:0}
.library{max-width:960px;margin:0 auto;padding:clamp(2rem,5vw,3.5rem) clamp(1.25rem,5vw,2rem) 5rem}
.library > header{margin-bottom:2.6rem}
.library h1{margin:0;font-family:Georgia,serif;font-weight:400;
  font-size:clamp(2rem,4vw,2.9rem);line-height:1.18;letter-spacing:-.02em}
.library .lede{margin:.7rem 0 0;color:var(--muted)}
.shelf{margin:0 0 3rem}
.shelf-head{margin-bottom:1.25rem}
.shelf h2{margin:0;font-family:Georgia,serif;font-weight:400;font-size:1.5rem}
.shelf .desc{margin:.35rem 0 0;color:var(--muted);font-size:.95rem}
.track{
  display:grid;grid-template-columns:56px minmax(0,1fr);gap:1.1rem;
  align-items:start;padding:1.4rem 0;border-top:1px solid var(--line);
}
.cover{
  width:56px;height:56px;display:grid;place-items:center;border-radius:2px;
  background:var(--paper-deep);border:1px solid var(--line);
  color:var(--brass);font-family:Georgia,serif;font-size:1.5rem;
}
.track-name{margin:0;font-size:1.02rem;font-weight:600;line-height:1.4}
.track-meta{margin:.1rem 0 .8rem;font-size:.85rem;color:var(--muted)}
.track audio{width:100%;height:38px;display:block}
.empty{padding:3rem 0;color:var(--muted);font-family:Georgia,serif;font-size:1.2rem}

@media (max-width:820px){
  .stage{grid-template-columns:1fr;align-content:center;gap:2.75rem;padding-top:3rem}
  .intro .kicker{margin-top:2rem}
  .access{justify-self:start;max-width:none}
}
@media (prefers-reduced-motion:reduce){
  *{transition:none!important}
}
"""

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

_HEAD = (
    '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<style>' + _CSS + '</style></head><body>'
)


def _title(title: str) -> str:
    return f'<title>{ESC(title)}</title>'


def login_page() -> str:
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
    </div>
    <div class="rule" aria-hidden="true"><span></span><i></i><span></span></div>
    <p class="foot">AURA · Écoute privée</p>
  </section>
</div>
</body></html>"""


def catalog_page(principal: dict, collections: list[dict]) -> str:
    name = principal.get("email") or principal.get("name")
    parts = [
        _HEAD,
        _title("AURA — Bibliothèque"),
        '<header class="topbar"><div class="brand">', _BRAND,
        '<span class="word">AURA</span></div><div class="member">',
        f'<span>{ESC(name)}</span>',
        '<form method="post" action="/api/public/logout">',
        f'<input type="hidden" name="csrf_token" value="{ESC(principal["csrf"])}">',
        '<button class="text-button" type="submit">Déconnexion</button>',
        '</form></div></header>',
        '<main class="library"><header><h1>Bon retour.</h1>',
        '<p class="lede">Les livres publiés pour vous, prêts à écouter.</p></header>',
    ]
    published = [c for c in collections if c.get("items")]
    if not published:
        parts.append('<p class="empty">Aucun livre publié pour le moment.</p>')
    for col in published:
        parts.append('<section class="shelf"><div class="shelf-head">')
        parts.append(f'<h2>{ESC(col.get("title"))}</h2>')
        if col.get("description"):
            parts.append(f'<p class="desc">{ESC(col["description"])}</p>')
        parts.append('</div>')
        for item in col["items"]:
            label = str(item.get("display_name") or "?")
            initial = label.strip()[:1].upper() or "A"
            duration = item.get("duration_seconds")
            meta = "Livre audio"
            if duration:
                minutes, seconds = divmod(int(duration), 60)
                meta = f"{minutes} min {seconds:02d} s"
            parts.extend([
                '<article class="track">',
                f'<div class="cover" aria-hidden="true">{ESC(initial)}</div>',
                '<div><p class="track-name">', ESC(label), '</p>',
                f'<p class="track-meta">{ESC(meta)}</p>',
                f'<audio controls preload="metadata" src="{ESC(item["url"])}"></audio>',
                '</div></article>',
            ])
        parts.append('</section>')
    parts.append('</main></body></html>')
    return "".join(parts)
