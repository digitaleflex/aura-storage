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

/* ---- search + player -------------------------------------------------- */
.search-form{display:flex;gap:.6rem;align-items:center;margin-top:1.4rem;max-width:28rem}
.search-form input{flex:1;min-width:0;font:inherit;padding:.65rem .8rem;color:var(--ink);
  background:var(--sheet);border:1px solid var(--line);border-radius:3px}
.search-form input:focus-visible,.seek:focus-visible,select:focus-visible{
  outline:3px solid var(--brass);outline-offset:2px}
.search-form button{font:inherit;padding:.65rem 1rem;border:1px solid var(--ink);
  background:var(--ink);color:var(--sheet);border-radius:3px;cursor:pointer}
.shelf ul{list-style:none;margin:0;padding:0}
.track-button{
  display:grid;grid-template-columns:56px minmax(0,1fr) auto;gap:1.1rem;
  align-items:center;width:100%;text-align:left;font:inherit;color:inherit;
  background:none;border:0;border-top:1px solid var(--line);padding:1.1rem .6rem;
  border-radius:2px;cursor:pointer;
}
.track-button:hover{background:rgba(255,255,255,.55)}
.track-button:focus-visible{outline:3px solid var(--brass);outline-offset:-3px}
.track-button.playing{background:var(--paper-deep)}
.cover{background:hsl(var(--cover-h) 28% 88%);color:hsl(var(--cover-h) 42% 30%)}
.track-title{display:block;font-size:1.02rem;font-weight:600;line-height:1.35}
.track-author{display:block;margin-top:.1rem;font-size:.85rem;color:var(--muted)}
.track-progress{display:block;height:3px;margin-top:.55rem;background:var(--line);border-radius:3px;overflow:hidden}
.track-progress i{display:block;height:100%;background:var(--brass);width:0}
.track-duration{font-size:.85rem;color:var(--muted);font-variant-numeric:tabular-nums}
#player{display:none}
.player-bar{
  position:fixed;left:0;right:0;bottom:0;z-index:10;
  background:rgba(255,253,248,.97);border-top:1px solid var(--line);
  box-shadow:0 -8px 24px -20px rgba(27,43,58,.5);
  padding:.85rem clamp(1rem,4vw,2rem);
  display:grid;grid-template-columns:minmax(8rem,1fr) minmax(14rem,2fr) minmax(8rem,1fr);
  gap:1.2rem;align-items:center;
}
.player-bar[hidden]{display:none}
.now-title{margin:0;font-size:.95rem;font-weight:600;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.now-author{margin:0;font-size:.8rem;color:var(--muted);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.transport{display:flex;align-items:center;justify-content:center;gap:.35rem}
.icon-button{font:inherit;line-height:1;min-width:38px;min-height:38px;
  border:1px solid transparent;background:none;color:var(--ink);border-radius:3px;
  cursor:pointer;font-size:1.05rem}
.icon-button:hover{border-color:var(--line);background:var(--paper)}
.icon-button:focus-visible{outline:3px solid var(--brass);outline-offset:2px}
.icon-button.main{background:var(--ink);color:var(--sheet);min-width:44px;min-height:44px;
  border-radius:50%;font-size:1.15rem}
.seek-row{grid-column:1/-1;display:flex;align-items:center;gap:.7rem;grid-row:2}
.seek{flex:1;accent-color:var(--brass);width:100%}
.time{font-size:.78rem;color:var(--muted);font-variant-numeric:tabular-nums;min-width:8rem;text-align:center}
.player-right{display:flex;align-items:center;justify-content:flex-end;gap:.6rem}
.player-right select,.player-right input[type=range]{font:inherit;font-size:.85rem}
.player-right input[type=range]{width:5rem;accent-color:var(--brass)}
.library{padding-bottom:9rem}

@media (max-width:820px){
  .player-bar{grid-template-columns:1fr auto;gap:.6rem .8rem}
  .player-right{grid-column:1/-1;justify-content:space-between}
  .seek-row{grid-row:3}
  .transport{justify-content:flex-end}
}
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


_PLAYER_JS = """
<script>
(function(){
  const csrf = "__CSRF__";
  const audio = document.getElementById('player');
  const bar = document.getElementById('player-bar');
  const tracks = Array.from(document.querySelectorAll('.track-button'));
  const seek = document.getElementById('seek');
  const nowTitle = document.getElementById('now-title');
  const nowAuthor = document.getElementById('now-author');
  const timeNow = document.getElementById('time-now');
  const timeTotal = document.getElementById('time-total');
  const playToggle = document.getElementById('play-toggle');
  let index = -1, lastSaved = 0, retried = false;

  function fmt(value){
    if(!isFinite(value) || value < 0) value = 0;
    const m = Math.floor(value / 60), s = Math.floor(value % 60);
    return m + ':' + String(s).padStart(2, '0');
  }
  function save(force){
    if(index < 0) return;
    const track = tracks[index];
    const position = audio.currentTime || 0;
    if(!force && Math.abs(position - lastSaved) < 5) return;
    lastSaved = position;
    const fill = track.querySelector('.track-progress i');
    if(fill && audio.duration){
      fill.style.width = Math.min(100, position / audio.duration * 100) + '%';
    }
    fetch('/api/public/progress', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({object_id: track.dataset.objectId,
                            position_seconds: Math.floor(position)})
    }).catch(function(){});
  }
  function nowPlaying(){
    if(index < 0) return;
    const track = tracks[index];
    nowTitle.textContent = track.dataset.title;
    nowAuthor.textContent = track.dataset.author || 'Livre audio';
    timeTotal.textContent = fmt(audio.duration);
    if('mediaSession' in navigator){
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track.dataset.title, artist: track.dataset.author || 'AURA'
      });
    }
  }
  function play(i){
    if(i < 0 || i >= tracks.length) return;
    if(i === index){ toggle(); return; }
    if(index >= 0) tracks[index].classList.remove('playing');
    index = i; retried = false; lastSaved = 0;
    const track = tracks[i];
    track.classList.add('playing');
    audio.src = track.dataset.url;
    audio.load();
    const start = parseFloat(track.dataset.progress || '0');
    audio.addEventListener('loadedmetadata', function ready(){
      if(isFinite(start) && start > 0 && start < (audio.duration || Infinity)){
        audio.currentTime = start;
      }
      audio.removeEventListener('loadedmetadata', ready);
    });
    audio.play().catch(function(){});
    bar.hidden = false;
    nowPlaying();
  }
  function toggle(){
    if(index < 0 && tracks.length){ play(0); return; }
    if(audio.paused){ audio.play().catch(function(){}); }
    else { save(true); audio.pause(); }
    playToggle.textContent = audio.paused ? 'Lecture' : 'Pause';
  }
  function stop(){
    save(true); audio.pause(); audio.removeAttribute('src'); audio.load();
    if(index >= 0) tracks[index].classList.remove('playing');
    index = -1; bar.hidden = true;
  }
  playToggle.addEventListener('click', toggle);
  document.getElementById('prev').addEventListener('click', function(){ play(index - 1); });
  document.getElementById('next').addEventListener('click', function(){ play(index + 1); });
  document.getElementById('back15').addEventListener('click', function(){
    audio.currentTime = Math.max(0, (audio.currentTime || 0) - 15);
  });
  document.getElementById('fwd15').addEventListener('click', function(){
    audio.currentTime = Math.min(audio.duration || Infinity, (audio.currentTime || 0) + 15);
  });
  document.getElementById('close').addEventListener('click', stop);
  seek.addEventListener('input', function(){
    if(isFinite(audio.duration)) audio.currentTime = Number(seek.value);
  });
  document.getElementById('speed').addEventListener('change', function(e){
    audio.playbackRate = parseFloat(e.target.value);
  });
  document.getElementById('volume').addEventListener('input', function(e){
    audio.volume = parseFloat(e.target.value);
  });
  audio.addEventListener('play', function(){ playToggle.textContent = 'Pause'; });
  audio.addEventListener('pause', function(){ playToggle.textContent = 'Lecture'; save(true); });
  audio.addEventListener('timeupdate', function(){
    if(!isFinite(audio.duration)) return;
    seek.value = audio.currentTime;
    timeNow.textContent = fmt(audio.currentTime);
    timeTotal.textContent = fmt(audio.duration);
    save(false);
  });
  audio.addEventListener('loadedmetadata', nowPlaying);
  audio.addEventListener('ended', function(){
    save(true);
    if(index + 1 < tracks.length) play(index + 1); else stop();
  });
  audio.addEventListener('error', function(){
    if(index < 0 || retried) return;
    retried = true;
    const track = tracks[index];
    const position = audio.currentTime || 0;
    audio.src = track.dataset.url + '?refresh=' + Date.now();
    audio.load();
    audio.currentTime = position;
    audio.play().catch(function(){});
  });
  tracks.forEach(function(button, i){
    button.addEventListener('click', function(){ play(i); });
  });
  window.addEventListener('beforeunload', function(){ save(true); });
  document.addEventListener('visibilitychange', function(){
    if(document.hidden) save(true);
  });
  document.addEventListener('keydown', function(e){
    if(['INPUT','SELECT','TEXTAREA'].indexOf(e.target.tagName) >= 0) return;
    if(e.code === 'Space'){ e.preventDefault(); toggle(); }
    else if(e.key === 'ArrowRight'){ e.preventDefault(); audio.currentTime = (audio.currentTime||0) + 15; }
    else if(e.key === 'ArrowLeft'){ e.preventDefault(); audio.currentTime = Math.max(0,(audio.currentTime||0) - 15); }
    else if(e.key === 'Escape'){ stop(); }
  });
  if('mediaSession' in navigator){
    navigator.mediaSession.setActionHandler('play', function(){ audio.play().catch(function(){}); });
    navigator.mediaSession.setActionHandler('pause', function(){ audio.pause(); });
    navigator.mediaSession.setActionHandler('seekbackward', function(){ audio.currentTime = Math.max(0,(audio.currentTime||0)-15); });
    navigator.mediaSession.setActionHandler('seekforward', function(){ audio.currentTime = (audio.currentTime||0)+15; });
    navigator.mediaSession.setActionHandler('previoustrack', function(){ play(index-1); });
    navigator.mediaSession.setActionHandler('nexttrack', function(){ play(index+1); });
  }
})();
</script>
"""


def _duration_text(seconds) -> str:
    if not seconds:
        return "Livre audio"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes} min {remainder:02d} s"


def catalog_page(principal: dict, collections: list[dict], query: str = "") -> str:
    name = principal.get("email") or principal.get("name")
    csrf = str(principal.get("csrf") or "")
    parts = [
        _HEAD,
        _title("AURA — Bibliothèque"),
        '<header class="topbar"><div class="brand">', _BRAND,
        '<span class="word">AURA</span></div><div class="member">',
        f'<span>{ESC(name)}</span>',
        '<form method="post" action="/api/public/logout">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<button class="text-button" type="submit">Déconnexion</button>',
        '</form></div></header>',
        '<main class="library"><header><h1>Bon retour.</h1>',
        '<p class="lede">Vos livres publiés, prêts à écouter.</p>',
        '<form class="search-form" method="get" action="/">',
        f'<input type="search" name="q" value="{ESC(query)}" '
        'placeholder="Rechercher un titre ou un auteur" aria-label="Rechercher un livre">',
        '<button type="submit">Rechercher</button></form></header>',
    ]
    published = [c for c in collections if c.get("items")]
    if not published:
        parts.append('<p class="empty">Aucun livre ne correspond à cette recherche.</p>')
    for col in published:
        parts.append('<section class="shelf"><div class="shelf-head">')
        parts.append(f'<h2>{ESC(col.get("title"))}</h2>')
        if col.get("description"):
            parts.append(f'<p class="desc">{ESC(col["description"])}</p>')
        parts.append('</div><ul>')
        for item in col["items"]:
            label = str(item.get("display_name") or "Livre")
            stem = label.rsplit(".", 1)[0] if "." in label else label
            if " - " in stem:
                author, title = stem.split(" - ", 1)
            else:
                author, title = "", stem
            initial = title.strip()[:1].upper() or "A"
            hue = sum(ord(c) for c in title) * 37 % 360
            duration = float(item.get("duration_seconds") or 0)
            progress = float(item.get("progress_seconds") or 0)
            pct = min(100.0, progress / duration * 100) if duration else 0.0
            parts.extend([
                '<li><button type="button" class="track-button"',
                f' data-url="{ESC(item["url"])}"',
                f' data-object-id="{ESC(item["id"])}"',
                f' data-title="{ESC(title.strip())}"',
                f' data-author="{ESC(author.strip())}"',
                f' data-duration="{duration:.0f}"',
                f' data-progress="{progress:.0f}"',
                f' style="--cover-h:{hue}"',
                ' aria-label="Écouter">',
                f'<span class="cover" aria-hidden="true">{ESC(initial)}</span>',
                '<span><span class="track-title">', ESC(title.strip()), '</span>',
                f'<span class="track-author">{ESC(author.strip() or "Livre audio")}</span>',
                f'<span class="track-progress"><i style="width:{pct:.1f}%"></i></span></span>',
                f'<span class="track-duration">{ESC(_duration_text(duration))}</span>',
                '</button></li>',
            ])
        parts.append('</ul></section>')
    parts.extend([
        '<audio id="player" preload="none"></audio>',
        '<div class="player-bar" id="player-bar" hidden role="region" '
        'aria-label="Lecteur audio">',
        '<div><p class="now-title" id="now-title" aria-live="polite"></p>',
        '<p class="now-author" id="now-author"></p></div>',
        '<div class="transport">',
        '<button type="button" class="icon-button" id="prev" aria-label="Titre précédent">Préc.</button>',
        '<button type="button" class="icon-button" id="back15" aria-label="Reculer de 15 secondes">−15 s</button>',
        '<button type="button" class="icon-button main" id="play-toggle" aria-label="Lecture ou pause">Lecture</button>',
        '<button type="button" class="icon-button" id="fwd15" aria-label="Avancer de 15 secondes">+15 s</button>',
        '<button type="button" class="icon-button" id="next" aria-label="Titre suivant">Suiv.</button>',
        '</div>',
        '<div class="player-right">',
        '<label for="speed">Vitesse</label>',
        '<select id="speed" aria-label="Vitesse de lecture">',
        '<option value="0.75">0,75×</option><option value="1" selected>1×</option>',
        '<option value="1.25">1,25×</option><option value="1.5">1,5×</option>',
        '<option value="1.75">1,75×</option><option value="2">2×</option>',
        '</select>',
        '<label for="volume">Volume</label>',
        '<input id="volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volume">',
        '<button type="button" class="icon-button" id="close" aria-label="Fermer le lecteur">Fermer</button>',
        '</div>',
        '<div class="seek-row"><span class="time" id="time-now">0:00</span>',
        '<input class="seek" id="seek" type="range" min="0" max="100" value="0" '
        'step="0.1" aria-label="Position dans le livre">',
        '<span class="time" id="time-total">0:00</span></div>',
        '</div>',
        _PLAYER_JS.replace("__CSRF__", ESC(csrf)),
        '</main></body></html>',
    ])
    return "".join(parts)
