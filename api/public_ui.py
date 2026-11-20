"""HTML for the public portal.

Deliberately dependency-free: pages are served by the API on the public host,
with no JavaScript bundle and no external font/CDN. The visual direction is a
warm library — ivory paper, night ink, brass accents, one clear action.
"""
import html
import json
from urllib.parse import urlencode

ESC = lambda value: html.escape(str(value if value is not None else ""), quote=True)

_CSS = """
:root{
  --bg:#F8F6F1; --bg-deep:#EFEAE1; --surface:#FFFEFC;
  --ink:#1D2B39; --text:#292929; --muted:#737373; --soft:#5f6670;
  --bronze:#956D35; --line:#E9E4DA; --line-strong:#D9D2C5;
  --focus:#956D35;
}
*{box-sizing:border-box}
html{min-height:100%}
body{
  margin:0; min-height:100vh; color:var(--ink);
  font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:16px; line-height:1.6;
  background:
    radial-gradient(circle at 12% 8%, rgba(255,255,255,.9) 0, transparent 42%),
    radial-gradient(circle at 88% 92%, rgba(149,109,53,.08) 0, transparent 38%),
    var(--bg);
}
a{color:inherit}
button,input,select{font:inherit}
.nowrap{white-space:nowrap}
.serif{font-family:Georgia,"Iowan Old Style","Palatino Linotype",serif}

/* ---- shared brand ---------------------------------------------------- */
.brand{display:inline-flex;align-items:center;gap:.65rem;font-size:.8rem;
  letter-spacing:.22em;font-weight:700;text-transform:uppercase;color:var(--ink)}
.brand svg{width:30px;height:30px;flex:none}
.brand .word{display:inline-block;transform:translateY(.02em)}
.eyebrow{margin:0 0 .6rem;font-size:.72rem;letter-spacing:.18em;
  text-transform:uppercase;color:var(--bronze);font-weight:700}

/* ---- login ----------------------------------------------------------- */
.stage{
  min-height:100vh; display:grid; gap:clamp(2.5rem,6vw,6rem);
  grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);
  align-items:center; max-width:1120px; margin:0 auto;
  padding:clamp(2rem,6vh,5rem) clamp(1.25rem,5vw,3rem);
}
.intro .kicker{margin:2.6rem 0 .9rem;font-size:.78rem;letter-spacing:.2em;
  text-transform:uppercase;color:var(--bronze);font-weight:700}
.intro h1{
  margin:0; font-family:Georgia,"Iowan Old Style","Palatino Linotype",serif;
  font-weight:400; font-size:clamp(2.5rem,5.2vw,4rem); line-height:1.13;
  letter-spacing:-.02em;
}
.intro .lede{max-width:32rem;margin:1.4rem 0 0;color:var(--muted);font-size:1.06rem}
.wave{display:flex;align-items:center;gap:5px;height:34px;margin-top:2.6rem;
  color:var(--bronze);opacity:.85}
.wave i{display:block;width:3px;border-radius:3px;background:currentColor}
.wave i:nth-child(1){height:8px}.wave i:nth-child(2){height:18px}
.wave i:nth-child(3){height:30px}.wave i:nth-child(4){height:14px}
.wave i:nth-child(5){height:24px}.wave i:nth-child(6){height:9px}
.wave i:nth-child(7){height:16px}
.access{max-width:26rem;width:100%;justify-self:end}
.panel{
  background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:clamp(1.75rem,3vw,2.5rem);
  box-shadow:0 18px 40px -28px rgba(29,43,57,.35), 0 2px 0 rgba(29,43,57,.03);
}
.panel h2{margin:0;font-family:Georgia,serif;font-weight:400;
  font-size:1.75rem;line-height:1.25;letter-spacing:-.01em}
.hint{margin:.85rem 0 1.9rem;color:var(--muted);font-size:.96rem;line-height:1.6}
.google-button{
  display:flex;align-items:center;justify-content:center;gap:.75rem;
  width:100%;min-height:52px;padding:.7rem 1rem;border-radius:10px;
  background:#fff;border:1px solid var(--line-strong);
  box-shadow:0 2px 0 rgba(29,43,57,.06);
  font-size:1rem;font-weight:600;text-decoration:none;color:var(--ink);
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.google-button svg{width:20px;height:20px;flex:none}
.google-button:hover{border-color:rgba(149,109,53,.55);
  box-shadow:0 8px 18px -10px rgba(29,43,57,.35);transform:translateY(-1px)}
.google-button:active{transform:translateY(0);box-shadow:0 1px 0 rgba(29,43,57,.08)}
.google-button:focus-visible,.text-button:focus-visible,.pill:focus-visible,
.track-button:focus-visible,.resume-card button:focus-visible,
.search-form input:focus-visible,.search-form button:focus-visible,
.icon-button:focus-visible,.pill-button:focus-visible,.seek:focus-visible,
select:focus-visible,input[type=range]:focus-visible,.view-link:focus-visible,
.facet:focus-visible,.discovery a:focus-visible{
  outline:3px solid var(--focus);outline-offset:2px}
.fine{margin:1.25rem 0 0;font-size:.83rem;color:var(--muted);text-align:center}
.rule{display:flex;align-items:center;gap:.9rem;margin:1.6rem 0 .9rem;color:var(--bronze)}
.rule span{height:1px;background:var(--line);flex:1}
.rule i{width:5px;height:5px;background:var(--bronze);transform:rotate(45deg)}
.foot{margin:0;text-align:center;font-size:.78rem;letter-spacing:.08em;color:var(--muted)}

/* ---- catalogue shell ------------------------------------------------- */
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:1rem;
  flex-wrap:wrap;max-width:1120px;margin:0 auto;
  padding:1.25rem clamp(1.25rem,5vw,2rem) 1rem;
  border-bottom:1px solid var(--line);
}
.member{display:flex;align-items:center;gap:1rem;font-size:.9rem;color:var(--muted)}
.text-button{font:inherit;color:var(--ink);background:none;border:0;
  border-bottom:1px solid var(--bronze);padding:0 0 2px;cursor:pointer;border-radius:0}
.library{max-width:1120px;margin:0 auto;padding:clamp(1.8rem,4vw,3rem) clamp(1.25rem,5vw,2rem) 12rem}
.library-header{margin-bottom:1.6rem}
.library-header h1{margin:0;font-family:Georgia,serif;font-weight:400;
  font-size:clamp(2.1rem,4vw,3rem);line-height:1.15;letter-spacing:-.02em}
.library-header .lede{margin:.45rem 0 0;color:var(--muted);font-size:1.02rem}

/* ---- resume ---------------------------------------------------------- */
.resume-card{
  display:grid;grid-template-columns:120px minmax(0,1fr) auto;gap:1.25rem;align-items:center;
  margin:0 0 2.2rem;padding:1.2rem 1.3rem;border:1px solid var(--line);
  border-radius:16px;background:var(--surface);
  box-shadow:0 14px 34px -28px rgba(29,43,57,.45);
}
.resume-cover{width:120px;aspect-ratio:1;border-radius:10px;position:relative;overflow:hidden;
  display:grid;place-items:center;font-family:Georgia,serif;font-size:2.4rem;
  background:hsl(var(--cover-h) 28% 86%);color:hsl(var(--cover-h) 38% 28%);border:1px solid var(--line)}
.resume-cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.resume-copy h2{margin:.1rem 0 .15rem;font-family:Georgia,serif;font-weight:400;
  font-size:clamp(1.35rem,2.2vw,1.9rem);line-height:1.2}
.resume-copy p{margin:0;color:var(--muted)}
.resume-meta{margin-top:.7rem;font-size:.9rem;color:var(--soft)}
.resume-progress{height:6px;border-radius:999px;background:var(--line);overflow:hidden;margin-top:.7rem;max-width:32rem}
.resume-progress i{display:block;height:100%;background:var(--bronze)}
.resume-actions{display:flex;flex-direction:column;gap:.5rem;align-items:flex-end}
.primary-button{font:inherit;font-weight:600;color:var(--surface);background:var(--ink);
  border:1px solid var(--ink);border-radius:999px;padding:.75rem 1.2rem;cursor:pointer}
.primary-button:hover{background:#24384b;border-color:#24384b}
.secondary-link{font-size:.9rem;color:var(--muted);text-decoration:none;border-bottom:1px solid transparent}
.secondary-link:hover{color:var(--ink);border-color:var(--bronze)}

/* ---- search + controls ----------------------------------------------- */
.search-form{display:flex;gap:.6rem;align-items:center;margin-top:1.1rem;max-width:34rem}
.search-form input{flex:1;min-width:0;font:inherit;padding:.7rem .9rem;color:var(--ink);
  background:var(--surface);border:1px solid var(--line);border-radius:10px}
.search-form button{font:inherit;padding:.7rem 1rem;border:1px solid var(--ink);
  background:var(--ink);color:var(--surface);border-radius:10px;cursor:pointer}
.controls-block{margin:1.2rem 0 0;display:grid;gap:.75rem}
.control-row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.control-row .label{font-size:.76rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);font-weight:700;margin-right:.25rem}
.view-link,.facet,.pill{font:inherit;font-size:.9rem;padding:.38rem .8rem;border:1px solid var(--line);
  border-radius:999px;background:var(--surface);color:var(--ink);text-decoration:none;cursor:pointer}
.view-link:hover,.facet:hover{border-color:rgba(149,109,53,.55)}
.view-link[aria-current=true],.facet[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.facet small,.pill small{font-size:.78em;opacity:.8}
.pill-static{cursor:default;color:var(--soft);background:rgba(255,254,252,.7)}
.facet-clear{font-size:.88rem;color:var(--muted);text-decoration:none;border-bottom:1px solid transparent;margin-left:.2rem}
.facet-clear:hover{color:var(--ink);border-color:var(--bronze)}
.facet-tools{width:100%;margin-top:.1rem}
.facet-search{width:min(100%,22rem);font:inherit;font-size:.9rem;padding:.55rem .75rem;
  border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink)}
.facet-toggle{font-size:.88rem;color:var(--muted);padding:0;margin-left:.1rem}
.facet[hidden]{display:none !important}
.discovery{display:flex;flex-wrap:wrap;gap:.5rem;margin:1.2rem 0 2.2rem}
.discovery a{font:inherit;font-size:.9rem;padding:.55rem .95rem;border-radius:999px;
  border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);text-decoration:none}
.discovery a:hover{border-color:rgba(149,109,53,.55);background:#fff}

/* ---- shelves / tracks ------------------------------------------------ */
.shelf{margin:0 0 2.8rem}
.shelf-head{margin-bottom:1rem}
.shelf h2{margin:0;font-family:Georgia,serif;font-weight:400;font-size:1.55rem}
.shelf .desc{margin:.3rem 0 0;color:var(--muted);font-size:.95rem}
.shelf ul{list-style:none;margin:0;padding:0}
.track-button{
  display:grid;grid-template-columns:60px minmax(0,1fr) auto;gap:1rem;
  align-items:center;width:100%;text-align:left;color:inherit;
  background:none;border:0;border-top:1px solid var(--line);padding:1rem .5rem;
  border-radius:8px;cursor:pointer;
}
.track-button:hover{background:rgba(255,255,255,.55)}
.track-button.playing{background:rgba(149,109,53,.08)}
.cover{width:60px;height:60px;display:grid;place-items:center;border-radius:8px;
  position:relative;overflow:hidden;border:1px solid var(--line);
  background:hsl(var(--cover-h) 28% 88%);color:hsl(var(--cover-h) 40% 30%);
  font-family:Georgia,serif;font-size:1.5rem}
.cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.track-title{display:block;font-size:1.02rem;font-weight:600;line-height:1.35}
.track-author{display:block;margin-top:.1rem;font-size:.86rem;color:var(--muted)}
.track-progress{display:block;height:4px;margin-top:.55rem;background:var(--line);border-radius:999px;overflow:hidden}
.track-progress i{display:block;height:100%;background:var(--bronze);width:0}
.track-duration{font-size:.85rem;color:var(--muted);font-variant-numeric:tabular-nums}
.empty{padding:3rem 0;color:var(--muted);font-family:Georgia,serif;font-size:1.2rem}
.empty-state{margin:1rem 0 3rem;padding:2rem 1.6rem;border:1px solid var(--line);border-radius:16px;background:var(--surface);max-width:42rem}
.empty-state h2{margin:.1rem 0 .4rem;font-family:Georgia,serif;font-weight:400;font-size:1.7rem}
.empty-state p{margin:.2rem 0;color:var(--muted)}

.view-grid .shelf ul{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:1rem}
.view-grid .track-button{display:block;border:1px solid var(--line);border-radius:12px;
  padding:.9rem;background:var(--surface)}
.view-grid .cover{width:100%;height:auto;aspect-ratio:1;margin-bottom:.8rem;font-size:2.5rem}
.view-grid .track-duration{display:block;margin-top:.5rem}

/* immersive hero */
.hero{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr);gap:2rem;
  align-items:center;margin:0 0 2.6rem;padding:1.8rem;background:var(--surface);
  border:1px solid var(--line);border-radius:16px}
.hero .big-cover{width:100%;aspect-ratio:1;border-radius:12px;display:grid;
  place-items:center;font-family:Georgia,serif;font-size:4.2rem;
  background:hsl(var(--cover-h) 28% 84%);color:hsl(var(--cover-h) 40% 28%);
  position:relative;overflow:hidden;box-shadow:0 16px 30px -24px rgba(29,43,57,.55)}
.hero .big-cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hero h2{font-family:Georgia,serif;font-weight:400;font-size:clamp(1.8rem,4vw,2.8rem);
  line-height:1.15;margin:.2rem 0 .4rem}
.hero p{color:var(--muted);margin:0 0 1.2rem}
.hero .launch{font:inherit;font-weight:600;padding:.8rem 1.3rem;border:0;border-radius:999px;
  background:var(--ink);color:var(--surface);cursor:pointer}

/* ---- player ---------------------------------------------------------- */
#player{display:none}
.library{padding-bottom:3rem}
body.has-player .library{padding-bottom:12.5rem}
.player-bar{
  position:fixed;left:0;right:0;bottom:0;z-index:20;
  background:rgba(255,254,252,.985);backdrop-filter:blur(10px);
  border-top:1px solid var(--line);
  box-shadow:0 -12px 30px -24px rgba(29,43,57,.45);
  padding:.7rem clamp(1rem,3vw,1.6rem) calc(.7rem + env(safe-area-inset-bottom));
  display:grid;grid-template-columns:minmax(220px,1.1fr) minmax(320px,1.6fr) minmax(220px,1.2fr);
  grid-template-areas:"now center actions";
  gap:.6rem 1rem;align-items:center;
}
.player-bar[hidden]{display:none}
.player-now{grid-area:now;display:flex;align-items:center;gap:.75rem;min-width:0}
.player-now-btn{display:flex;align-items:center;gap:.75rem;min-width:0;background:none;border:0;padding:0;color:inherit;text-align:left;cursor:pointer}
.player-cover{display:grid;place-items:center;width:56px;height:56px;flex:none;border-radius:8px;
  position:relative;overflow:hidden;background:var(--bg-deep);border:1px solid var(--line);
  font-family:Georgia,serif;font-size:1.35rem;color:var(--bronze)}
.player-cover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.now-text{min-width:0}
.now-title{margin:0;font-size:.98rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.now-author{margin:.08rem 0 0;font-size:.82rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player-center{grid-area:center;display:grid;gap:.35rem;min-width:0}
.transport{display:flex;align-items:center;justify-content:center;gap:.25rem;flex-wrap:wrap}
.seek-row{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.6rem}
.seek{width:100%;height:6px;accent-color:var(--bronze);cursor:pointer}
.time{font-size:.78rem;color:var(--muted);font-variant-numeric:tabular-nums;min-width:2.8rem}
.time.end{text-align:right}
.icon-button,.pill-button{font:inherit;color:var(--ink);background:none;border:1px solid transparent;
  cursor:pointer;border-radius:8px;transition:background .15s ease,border-color .15s ease,color .15s ease}
.icon-button{line-height:1;min-width:40px;min-height:40px;display:inline-flex;align-items:center;justify-content:center;padding:.35rem}
.icon-button:hover,.pill-button:hover{border-color:var(--line);background:var(--bg)}
.icon-button.main{background:var(--ink);color:var(--surface);min-width:50px;min-height:50px;
  border-radius:999px;border-color:var(--ink);font-weight:700;font-size:.9rem;padding:0 1rem}
.icon-button.main:hover{background:#24384b;border-color:#24384b}
.icon-button.skip{font-size:.95rem;font-weight:600;min-width:42px;padding:.2rem .35rem}
.icon-button.main span[aria-hidden]{font-size:1.15rem;line-height:1}
.icon-button[aria-pressed="true"],.pill-button[aria-pressed="true"],.icon-button[aria-expanded="true"],.pill-button[aria-expanded="true"]{
  background:var(--bg-deep);border-color:rgba(149,109,53,.35);color:var(--bronze)}
.player-actions{grid-area:actions;display:flex;align-items:center;justify-content:flex-end;gap:.4rem;flex-wrap:wrap;min-width:0}
.control-group{display:inline-flex;align-items:center;gap:.3rem}
.control-group label{font-size:.74rem;color:var(--muted)}
.player-actions select{font:inherit;font-size:.82rem;color:var(--ink);background:var(--surface);
  border:1px solid var(--line);border-radius:8px;min-height:34px;padding:.15rem .4rem}
.player-actions input[type=range]{width:4.8rem;accent-color:var(--bronze)}
.utility-buttons{display:inline-flex;align-items:center;gap:.2rem}
.player-status{position:absolute;left:50%;bottom:.15rem;transform:translateX(-50%);
  margin:0;font-size:.75rem;color:var(--bronze);text-align:center;max-width:80%}
.player-status:empty{display:none}

/* overlays */
.queue-panel{position:fixed;right:1rem;bottom:calc(7.8rem + env(safe-area-inset-bottom));
  width:min(22rem,calc(100vw - 2rem));max-height:50vh;overflow:hidden;
  background:var(--surface);border:1px solid var(--line);border-radius:12px;
  box-shadow:0 18px 40px -24px rgba(29,43,57,.5);padding:0;z-index:30;display:flex;flex-direction:column}
.queue-panel[hidden]{display:none}
.queue-panel-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  padding:.55rem .5rem .45rem .75rem;border-bottom:1px solid var(--line);background:var(--surface);position:sticky;top:0}
.queue-panel h3{font-size:.78rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);margin:0}
.queue-panel .panel-close{min-width:34px;min-height:34px;font-size:1.2rem;line-height:1;border-radius:8px}
.queue-panel .panel-list{overflow:auto;padding:.4rem .45rem .55rem;max-height:calc(50vh - 3rem)}
.queue-panel .panel-list button,.queue-panel .panel-list p{display:block;width:100%;text-align:left;font:inherit;font-size:.9rem;
  padding:.55rem .55rem;border:0;background:none;color:var(--ink);cursor:pointer;border-radius:8px;margin:0}
.queue-panel .panel-list button:hover{background:var(--bg)}
.queue-panel .panel-list button.playing{background:rgba(149,109,53,.1);font-weight:600}
.queue-panel .panel-list button.active{background:rgba(149,109,53,.16);color:var(--bronze);font-weight:600}
.queue-panel .panel-list button.playing.active{box-shadow:inset 3px 0 0 var(--bronze)}

/* immersive */
.full-player .player-bar{
  inset:0;border:0;padding:clamp(1.2rem,4vw,3rem);
  grid-template-columns:1fr;grid-template-areas:"now" "center" "actions";
  gap:1.1rem;justify-items:center;align-content:center;z-index:40;
  background:rgba(248,246,241,.995)
}
.full-player .player-now{width:min(100%,42rem);justify-content:center}
.full-player .player-now-btn{flex-direction:column;text-align:center;gap:1rem;width:100%}
.full-player .player-cover{width:min(46vw,22rem);height:min(46vw,22rem);font-size:5rem;border-radius:14px}
.full-player .now-text{max-width:100%}
.full-player .now-title{font-family:Georgia,serif;font-size:clamp(1.6rem,4vw,2.5rem);white-space:normal}
.full-player .now-author{font-size:1rem;white-space:normal}
.full-player .player-center{width:min(100%,42rem);gap:.7rem}
.full-player .transport{gap:.5rem}
.full-player .icon-button.main{min-width:64px;min-height:64px;font-size:1rem}
.full-player .player-actions{justify-content:center;max-width:min(100%,46rem)}
.full-player .queue-panel{bottom:1.2rem;z-index:50}

@media (max-width:980px){
  .player-bar{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"now center" "actions actions";gap:.45rem .75rem}
  .player-actions{justify-content:flex-start}
}
@media (max-width:820px){
  .stage{grid-template-columns:1fr;align-content:center;gap:2.75rem;padding-top:3rem}
  .access{justify-self:start;max-width:none}
  .resume-card{grid-template-columns:96px 1fr;grid-template-areas:"cover copy" "actions actions"}
  .resume-cover{grid-area:cover;width:96px}
  .resume-copy{grid-area:copy}
  .resume-actions{grid-area:actions;align-items:flex-start}
  .hero{grid-template-columns:1fr;gap:1.2rem;padding:1.3rem}
  .hero .big-cover{max-width:13rem}
}
@media (max-width:720px){
  body.has-player .library{padding-bottom:17rem}
  .player-bar{grid-template-columns:1fr;grid-template-areas:"now" "center" "actions";gap:.4rem;padding:.55rem .75rem calc(.55rem + env(safe-area-inset-bottom))}
  .transport{justify-content:center;width:100%;max-width:none;margin:0 auto;gap:.15rem;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:.1rem}
  .transport .icon-button{flex:0 0 auto;min-width:38px}
  .icon-button.skip{min-width:38px;font-size:.92rem}
  .icon-button.main{min-width:48px;min-height:48px}
  .player-actions{flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;
    padding-bottom:.1rem;scrollbar-width:thin;gap:.35rem}
  .player-actions::-webkit-scrollbar{height:6px}
  .control-group,.utility-buttons{flex:none}
  .player-actions select{max-width:7.5rem}
  .queue-panel{left:.75rem;right:.75rem;width:auto;bottom:calc(15.5rem + env(safe-area-inset-bottom));max-height:45vh}
  .queue-panel .panel-list{max-height:calc(45vh - 3rem)}
}
@media (max-width:420px){
  .transport{justify-content:flex-start}
  .seek-row{gap:.4rem}
  .time{min-width:2.4rem;font-size:.74rem}
  .control-group label{display:none}
  .player-actions select,.player-actions input[type=range]{font-size:.8rem}
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


_PLAYER_JS = r"""
<script>
(function(){
  const csrf = "__CSRF__";
  const audio = document.getElementById('player');
  const bar = document.getElementById('player-bar');
  const tracks = Array.from(document.querySelectorAll('.track-button'));
  if(!audio || !bar || !tracks.length){ return; }
  const seek = document.getElementById('seek');
  const nowTitle = document.getElementById('now-title');
  const nowAuthor = document.getElementById('now-author');
  const nowChapter = document.getElementById('now-chapter');
  const timeNow = document.getElementById('time-now');
  const timeTotal = document.getElementById('time-total');
  const playToggle = document.getElementById('play-toggle');
  const queuePanel = document.getElementById('queue-panel');
  const queueList = document.getElementById('queue-list');
  const chaptersPanel = document.getElementById('chapters-panel');
  const chaptersList = document.getElementById('chapters-list');
  const sleepSelect = document.getElementById('sleep');
  const statusLine = document.getElementById('player-status');
  const playerCover = document.getElementById('player-cover');
  const fullButton = document.getElementById('fullscreen');
  const closeButton = document.getElementById('close');
  const chapterData = JSON.parse((document.getElementById('chapters-data') || {textContent:'{}'}).textContent || '{}');
  let index = -1, lastSaved = 0, retries = 0, sleepTimer = null, endOfChapter = false;

  function fmt(value){
    if(!isFinite(value) || value < 0) value = 0;
    const h = Math.floor(value / 3600);
    const m = Math.floor((value % 3600) / 60);
    const s = Math.floor(value % 60);
    if(h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    return m + ':' + String(s).padStart(2,'0');
  }
  function chaptersFor(i){
    if(i < 0) return [];
    const id = tracks[i].dataset.objectId;
    const list = chapterData[id] || [];
    return Array.isArray(list) ? list : [];
  }
  function currentChapter(){
    const list = chaptersFor(index);
    if(!list.length || !isFinite(audio.currentTime)) return null;
    const t = audio.currentTime;
    for(let i = list.length - 1; i >= 0; i--){
      if(t >= (Number(list[i].start_seconds) || 0)) return {item: list[i], i: i};
    }
    return {item: list[0], i: 0};
  }
  function setCover(container, track){
    if(!container || !track) return;
    container.innerHTML = '';
    const initial = document.createElement('span');
    initial.textContent = (track.dataset.title || 'A').trim().slice(0,1).toUpperCase() || 'A';
    container.appendChild(initial);
    if(track.dataset.cover){
      const img = document.createElement('img');
      img.src = track.dataset.cover;
      img.alt = '';
      img.onerror = function(){ this.remove(); };
      container.appendChild(img);
    }
  }
  function updateChapterLabel(){
    if(!nowChapter){ return; }
    const cur = currentChapter();
    nowChapter.textContent = cur && cur.item ? ('Chapitre · ' + (cur.item.title || ('Chapitre ' + (cur.i + 1)))) : '';
  }
  function updateProgressUI(force){
    if(index < 0) return;
    const track = tracks[index];
    const pos = audio.currentTime || 0;
    const dur = isFinite(audio.duration) ? audio.duration : (parseFloat(track.dataset.duration || '0') || 0);
    if(seek){
      if(dur > 0){ seek.max = dur; }
      seek.value = pos;
    }
    if(timeNow) timeNow.textContent = fmt(pos);
    if(timeTotal) timeTotal.textContent = fmt(dur);
    const fill = track.querySelector('.track-progress i');
    if(fill && dur > 0){ fill.style.width = Math.min(100, (pos / dur) * 100) + '%'; }
    track.dataset.progress = String(Math.floor(pos));
    updateChapterLabel();
    highlightCurrentChapter(false);
    if(force || Math.abs(pos - lastSaved) >= 5){
      lastSaved = pos;
      fetch('/api/public/progress', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({object_id: track.dataset.objectId, position_seconds: Math.floor(pos)})
      }).catch(function(){});
    }
  }
  function setPlayState(isPlaying){
    if(!playToggle) return;
    playToggle.innerHTML = '<span aria-hidden="true">' + (isPlaying ? '⏸' : '▶') + '</span>';
    playToggle.setAttribute('aria-label', isPlaying ? 'Mettre en pause' : 'Lire');
    playToggle.setAttribute('title', isPlaying ? 'Mettre en pause' : 'Lecture');
  }
  function setFullscreenState(active){
    document.body.classList.toggle('full-player', !!active);
    if(fullButton){
      fullButton.setAttribute('aria-pressed', active ? 'true' : 'false');
      fullButton.setAttribute('aria-label', active ? 'Réduire le lecteur' : 'Agrandir le lecteur');
      fullButton.setAttribute('title', active ? 'Réduire le lecteur' : 'Agrandir le lecteur');
      fullButton.textContent = active ? 'Réduire' : 'Agrandir';
    }
    if(closeButton){
      if(active){
        closeButton.textContent = 'Réduire';
        closeButton.setAttribute('aria-label', 'Réduire le lecteur');
        closeButton.setAttribute('title', 'Revenir au mini-lecteur');
      } else {
        closeButton.textContent = 'Fermer';
        closeButton.setAttribute('aria-label', 'Fermer le lecteur');
        closeButton.setAttribute('title', 'Arrêter la lecture');
      }
    }
  }
  function resumeAt(start, expected){
    audio.addEventListener('loadedmetadata', function ready(){
      if(index !== expected) return;
      if(isFinite(start) && start > 0 && start < (audio.duration || Infinity)){
        audio.currentTime = start;
      }
      updateProgressUI(false);
    }, {once:true});
  }
  function syncTrackVisual(i){
    tracks.forEach(function(t, j){ t.classList.toggle('playing', j === i); });
    if(queueList){
      Array.from(queueList.children).forEach(function(node, j){ node.classList.toggle('playing', j === i); });
    }
  }
  function buildQueue(){
    if(!queueList) return;
    queueList.innerHTML = '';
    tracks.forEach(function(track, i){
      const item = document.createElement('button');
      item.type = 'button';
      item.textContent = track.dataset.title || 'Livre';
      item.addEventListener('click', function(){ play(i); });
      queueList.appendChild(item);
    });
  }
  function highlightCurrentChapter(scroll){
    if(!chaptersList) return;
    const cur = currentChapter();
    const buttons = Array.from(chaptersList.querySelectorAll('button[data-chapter-index]'));
    buttons.forEach(function(btn){
      const active = cur && String(cur.i) === btn.getAttribute('data-chapter-index');
      btn.classList.toggle('active', !!active);
      if(active && scroll){ try { btn.scrollIntoView({block:'nearest'}); } catch(e){} }
    });
  }
  function buildChapters(){
    if(!chaptersList || index < 0) return;
    chaptersList.innerHTML = '';
    const list = chaptersFor(index);
    if(!list.length){
      const empty = document.createElement('p');
      empty.className = 'track-author';
      empty.style.margin = '.4rem .5rem';
      empty.textContent = 'Aucun chapitre détecté dans ce fichier.';
      chaptersList.appendChild(empty);
      return;
    }
    list.forEach(function(chapter, ci){
      const item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('data-chapter-index', String(ci));
      const start = Number(chapter.start_seconds || 0);
      item.textContent = (chapter.title || ('Chapitre ' + (ci + 1))) + ' · ' + fmt(start);
      item.addEventListener('click', function(){
        audio.currentTime = start;
        audio.play().catch(function(){});
      });
      chaptersList.appendChild(item);
    });
    highlightCurrentChapter(true);
  }
  function setPanelState(button, panel, open){
    if(!button || !panel) return;
    panel.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function closePanels(){
    const qt = document.getElementById('queue-toggle');
    const ct = document.getElementById('chapters-toggle');
    setPanelState(qt, queuePanel, false);
    setPanelState(ct, chaptersPanel, false);
  }
  function panelsOpen(){
    return (queuePanel && !queuePanel.hidden) || (chaptersPanel && !chaptersPanel.hidden);
  }
  function nowPlaying(){
    if(index < 0) return;
    const track = tracks[index];
    if(nowTitle) nowTitle.textContent = track.dataset.title || 'Livre audio';
    if(nowAuthor) nowAuthor.textContent = track.dataset.author || 'Livre audio';
    const bigCover = document.getElementById('immersive-cover-host');
    if(bigCover && track.dataset.cover){
      let bigImg = bigCover.querySelector('img');
      if(!bigImg){
        bigImg = document.createElement('img');
        bigImg.alt = '';
        bigImg.onerror = function(){ this.remove(); };
        bigCover.appendChild(bigImg);
      }
      bigImg.src = track.dataset.cover;
    }
    setCover(playerCover, track);
    buildChapters();
    updateChapterLabel();
    if('mediaSession' in navigator){
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: track.dataset.title || 'Livre audio',
          artist: track.dataset.author || 'AURA'
        });
      } catch(e){}
    }
  }
  function selectTrack(i, autoplay){
    if(i < 0 || i >= tracks.length) return;
    index = i; retries = 0; lastSaved = 0; endOfChapter = false;
    if(statusLine) statusLine.textContent = '';
    const track = tracks[i];
    syncTrackVisual(i);
    audio.src = track.dataset.url;
    audio.load();
    const start = parseFloat(track.dataset.progress || '0') || 0;
    resumeAt(start, i);
    bar.hidden = false;
    document.body.classList.add('has-player');
    nowPlaying();
    updateProgressUI(false);
    if(autoplay) audio.play().catch(function(){});
  }
  function toggle(){
    if(index < 0 && tracks.length){ play(0); return; }
    if(audio.paused){ audio.play().catch(function(){}); }
    else { updateProgressUI(true); audio.pause(); }
  }
  function play(i){
    if(i < 0 || i >= tracks.length) return;
    if(i === index){ toggle(); return; }
    selectTrack(i, true);
  }
  function clearSleepTimer(){
    if(sleepTimer){ clearTimeout(sleepTimer); sleepTimer = null; }
    endOfChapter = false;
    if(sleepSelect) sleepSelect.value = '0';
  }
  function minimizeToMini(){
    setFullscreenState(false);
  }
  function stop(){
    clearSleepTimer();
    updateProgressUI(true);
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if(index >= 0) tracks[index].classList.remove('playing');
    if(queueList){ Array.from(queueList.children).forEach(function(n){ n.classList.remove('playing'); }); }
    index = -1;
    setFullscreenState(false);
    closePanels();
    bar.hidden = true;
    document.body.classList.remove('has-player');
    setPlayState(false);
    if(statusLine) statusLine.textContent = '';
  }

  if(playToggle) playToggle.addEventListener('click', toggle);
  function goToChapter(delta){
    var list = chaptersFor(index);
    if(!list.length) return;
    var cur = currentChapter();
    var i = cur ? cur.i : 0;
    var target = Math.max(0, Math.min(list.length - 1, i + delta));
    var start = Number(list[target].start_seconds || 0);
    audio.currentTime = start;
    audio.play().catch(function(){});
    buildChapters();
  }
  var prev = document.getElementById('prev'); if(prev) prev.addEventListener('click', function(){ play(index - 1); });
  var next = document.getElementById('next'); if(next) next.addEventListener('click', function(){ play(index + 1); });
  var prevChapter = document.getElementById('prev-chapter'); if(prevChapter) prevChapter.addEventListener('click', function(){ goToChapter(-1); });
  var nextChapter = document.getElementById('next-chapter'); if(nextChapter) nextChapter.addEventListener('click', function(){ goToChapter(1); });
  var back15 = document.getElementById('back15'); if(back15) back15.addEventListener('click', function(){ audio.currentTime = Math.max(0, (audio.currentTime || 0) - 15); });
  var fwd15 = document.getElementById('fwd15'); if(fwd15) fwd15.addEventListener('click', function(){
    var d = isFinite(audio.duration) ? audio.duration : Infinity;
    audio.currentTime = Math.min(d, (audio.currentTime || 0) + 15);
  });
  if(closeButton) closeButton.addEventListener('click', function(){
    if(document.body.classList.contains('full-player')){
      // In immersive mode, closing returns to the mini-player without interrupting playback.
      minimizeToMini();
    } else {
      stop();
    }
  });
  if(seek) seek.addEventListener('input', function(){ if(isFinite(audio.duration)) audio.currentTime = Number(seek.value); });
  var speed = document.getElementById('speed'); if(speed) speed.addEventListener('change', function(e){ audio.playbackRate = parseFloat(e.target.value || '1'); });
  var volume = document.getElementById('volume'); if(volume) volume.addEventListener('input', function(e){ audio.volume = parseFloat(e.target.value || '1'); });
  if(fullButton) fullButton.addEventListener('click', function(){ setFullscreenState(!document.body.classList.contains('full-player')); });
  var nowBtn = document.getElementById('player-now-button'); if(nowBtn) nowBtn.addEventListener('click', function(){ setFullscreenState(true); });
  var queueToggle = document.getElementById('queue-toggle');
  if(queueToggle && queuePanel){
    queueToggle.addEventListener('click', function(){
      var open = queuePanel.hidden;
      setPanelState(queueToggle, queuePanel, open);
      if(open) setPanelState(document.getElementById('chapters-toggle'), chaptersPanel, false);
    });
  }
  var chaptersToggle = document.getElementById('chapters-toggle');
  if(chaptersToggle && chaptersPanel){
    chaptersToggle.addEventListener('click', function(){
      var open = chaptersPanel.hidden;
      setPanelState(chaptersToggle, chaptersPanel, open);
      if(open) setPanelState(queueToggle, queuePanel, false);
      if(open) buildChapters();
    });
  }
  Array.from(document.querySelectorAll('.panel-close')).forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = btn.getAttribute('data-close-panel');
      if(id === 'chapters-panel') setPanelState(document.getElementById('chapters-toggle'), chaptersPanel, false);
      if(id === 'queue-panel') setPanelState(document.getElementById('queue-toggle'), queuePanel, false);
    });
  });
  document.addEventListener('click', function(e){
    if(!panelsOpen()) return;
    var t = e.target;
    var inQueue = queuePanel && queuePanel.contains(t);
    var inChapters = chaptersPanel && chaptersPanel.contains(t);
    var onQueueToggle = queueToggle && queueToggle.contains(t);
    var onChaptersToggle = chaptersToggle && chaptersToggle.contains(t);
    if(!inQueue && !inChapters && !onQueueToggle && !onChaptersToggle){
      closePanels();
    }
  });
  if(sleepSelect){
    sleepSelect.addEventListener('change', function(e){
      if(sleepTimer){ clearTimeout(sleepTimer); sleepTimer = null; }
      endOfChapter = false;
      var val = e.target.value;
      if(val === 'chapter'){
        endOfChapter = true;
        if(statusLine) statusLine.textContent = 'Arrêt prévu à la fin du chapitre.';
      } else if(val === 'custom'){
        var mins = parseFloat(window.prompt('Minuteur (minutes) :', '20') || '');
        if(isFinite(mins) && mins > 0){
          sleepTimer = setTimeout(function(){ audio.pause(); clearSleepTimer(); }, mins * 60000);
          if(statusLine) statusLine.textContent = 'Minuteur : ' + mins + ' min.';
        } else {
          sleepSelect.value = '0';
        }
      } else {
        var minutes = parseFloat(val);
        if(minutes > 0){
          sleepTimer = setTimeout(function(){ audio.pause(); clearSleepTimer(); }, minutes * 60000);
          if(statusLine) statusLine.textContent = 'Minuteur : ' + minutes + ' min.';
        } else if(statusLine && statusLine.textContent.indexOf('Minuteur') === 0){
          statusLine.textContent = '';
        }
      }
    });
  }

  audio.addEventListener('play', function(){ setPlayState(true); });
  audio.addEventListener('pause', function(){ setPlayState(false); updateProgressUI(true); });
  audio.addEventListener('timeupdate', function(){
    if(!isFinite(audio.duration)) return;
    updateProgressUI(false);
    if(endOfChapter){
      var cur = currentChapter();
      if(cur){
        var list = chaptersFor(index);
        var nextStart = (cur.i + 1 < list.length) ? Number(list[cur.i + 1].start_seconds || 0) : null;
        if(nextStart !== null && audio.currentTime >= nextStart - 0.25){
          endOfChapter = false;
          audio.pause();
          if(statusLine) statusLine.textContent = 'Fin du chapitre atteinte.';
          if(sleepSelect) sleepSelect.value = '0';
        } else if(nextStart === null && audio.duration && audio.currentTime >= audio.duration - 0.5){
          endOfChapter = false;
        }
      }
    }
  });
  audio.addEventListener('loadedmetadata', function(){
    if(seek && isFinite(audio.duration)) seek.max = audio.duration;
    if(timeTotal) timeTotal.textContent = fmt(audio.duration);
    updateChapterLabel();
  });
  audio.addEventListener('ended', function(){
    clearSleepTimer();
    updateProgressUI(true);
    if(index + 1 < tracks.length) play(index + 1); else stop();
  });
  audio.addEventListener('error', function(){
    if(index < 0 || retries >= 3) return;
    retries += 1;
    if(statusLine) statusLine.textContent = 'Connexion interrompue, reprise en cours…';
    var track = tracks[index];
    var position = audio.currentTime || parseFloat(track.dataset.progress || '0') || 0;
    var wait = 400 * retries;
    setTimeout(function(){
      audio.src = track.dataset.url + (track.dataset.url.indexOf('?') >= 0 ? '&' : '?') + 'refresh=' + Date.now();
      audio.load();
      resumeAt(position, index);
      audio.play().catch(function(){
        if(statusLine && retries >= 3){
          statusLine.textContent = 'Lecture indisponible. Réessayez plus tard.';
        }
      });
    }, wait);
  });
  audio.addEventListener('playing', function(){ retries = 0; if(statusLine && statusLine.textContent.indexOf('Connexion') === 0){ statusLine.textContent = ''; } });

  tracks.forEach(function(button, i){ button.addEventListener('click', function(){ play(i); }); });
  buildQueue();

  var resumeBtn = document.getElementById('resume-continue');
  if(resumeBtn){
    resumeBtn.addEventListener('click', function(){
      var i = parseInt(resumeBtn.getAttribute('data-track-index') || '-1', 10);
      if(i >= 0) play(i);
    });
  }
  var launch = document.getElementById('launch');
  if(launch){ launch.addEventListener('click', function(){
    var i = parseInt(launch.getAttribute('data-track-index') || '0', 10);
    play(i >= 0 ? i : 0);
  }); }

  var authorsToggle = document.getElementById('authors-toggle');
  if(authorsToggle){
    authorsToggle.addEventListener('click', function(){
      var expanded = authorsToggle.getAttribute('data-expanded') === 'true';
      var extras = Array.from(document.querySelectorAll('.facet-extra'));
      extras.forEach(function(el){
        if(expanded){
          el.hidden = true;
        } else {
          var match = el.getAttribute('data-match');
          el.hidden = (match === 'false');
        }
      });
      authorsToggle.setAttribute('data-expanded', expanded ? 'false' : 'true');
      authorsToggle.textContent = expanded ? (authorsToggle.getAttribute('data-more') || 'Voir tous les auteurs')
                                           : (authorsToggle.getAttribute('data-less') || 'Voir moins');
    });
  }
  var authorSearch = document.getElementById('author-search');
  if(authorSearch){
    authorSearch.addEventListener('input', function(){
      var q = (authorSearch.value || '').toLowerCase().trim();
      var extras = Array.from(document.querySelectorAll('.facet-extra'));
      var shownExtra = 0;
      Array.from(document.querySelectorAll('#author-facets .facet[data-author]')).forEach(function(el){
        var name = (el.getAttribute('data-author') || '');
        if(name === '*') return;
        var ok = !q || name.indexOf(q) >= 0;
        el.setAttribute('data-match', ok ? 'true' : 'false');
        if(el.classList.contains('facet-extra')){
          var expanded = authorsToggle && authorsToggle.getAttribute('data-expanded') === 'true';
          el.hidden = !(ok && (expanded || q));
          if(!el.hidden) shownExtra++;
        } else {
          el.hidden = !ok;
        }
      });
      if(authorsToggle){
        authorsToggle.hidden = !!q; // when searching, show all matches; hide toggle
      }
    });
  }

  var best = -1, bestProgress = 0;
  tracks.forEach(function(track, i){
    var value = parseFloat(track.dataset.progress || '0') || 0;
    if(value > bestProgress){ bestProgress = value; best = i; }
  });
  setPlayState(false);
  if(best >= 0) selectTrack(best, false);

  window.addEventListener('beforeunload', function(){ updateProgressUI(true); });
  document.addEventListener('visibilitychange', function(){ if(document.hidden) updateProgressUI(true); });
  document.addEventListener('keydown', function(e){
    if(['INPUT','SELECT','TEXTAREA'].indexOf(e.target.tagName) >= 0) return;
    if(e.code === 'Space'){ e.preventDefault(); toggle(); }
    else if(e.key === 'ArrowRight'){ e.preventDefault(); audio.currentTime = Math.min(isFinite(audio.duration)?audio.duration:Infinity, (audio.currentTime||0) + 15); }
    else if(e.key === 'ArrowLeft'){ e.preventDefault(); audio.currentTime = Math.max(0,(audio.currentTime||0) - 15); }
    else if(e.key === 'Escape'){
      if(panelsOpen()){ closePanels(); }
      else if(document.body.classList.contains('full-player')){ setFullscreenState(false); }
    }
  });
  if('mediaSession' in navigator){
    try {
      navigator.mediaSession.setActionHandler('play', function(){ audio.play().catch(function(){}); });
      navigator.mediaSession.setActionHandler('pause', function(){ audio.pause(); });
      navigator.mediaSession.setActionHandler('seekbackward', function(){ audio.currentTime = Math.max(0,(audio.currentTime||0)-15); });
      navigator.mediaSession.setActionHandler('seekforward', function(){ audio.currentTime = (audio.currentTime||0)+15; });
      navigator.mediaSession.setActionHandler('previoustrack', function(){ play(index-1); });
      navigator.mediaSession.setActionHandler('nexttrack', function(){ play(index+1); });
    } catch(e){}
  }
})();
</script>
"""


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


def _position_text(seconds) -> str:
    if not seconds:
        return "0:00"
    total = int(float(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _track_html(item: dict) -> str:
    label = str(item.get("title") or item.get("display_name") or "Livre")
    author = str(item.get("author") or "")
    initial = label.strip()[:1].upper() or "A"
    hue = sum(ord(c) for c in label) * 37 % 360
    duration = float(item.get("duration_seconds") or 0)
    progress = float(item.get("progress_seconds") or 0)
    pct = min(100.0, progress / duration * 100) if duration else 0.0
    cover = item.get("cover_url") or ""
    cover_inner = f'<span>{ESC(initial)}</span>'
    if cover:
        cover_inner += f'<img src="{ESC(cover)}" alt="" loading="lazy" onerror="this.remove()">'
    return "".join([
        '<li><button type="button" class="track-button"',
        f' data-url="{ESC(item.get("url") or "")}"',
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
        f'<span class="track-progress"><i style="width:{pct:.1f}%"></i></span>',
        '</span>',
        f'<span class="track-duration">{ESC(_duration_text(duration))}</span>',
        '</button></li>',
    ])


def catalog_page(
    principal: dict,
    collections: list[dict],
    query: str = "",
    view: str = "liste",
    authors: list[str] | None = None,
    active_author: str = "",
) -> str:
    authors = authors or []
    name = principal.get("email") or principal.get("name")
    csrf = str(principal.get("csrf") or "")

    def href(**changes):
        params = {}
        if query:
            params["q"] = query
        if view != "liste":
            params["vue"] = view
        if active_author:
            params["auteur"] = active_author
        for key, value in changes.items():
            if value in (None, ""):
                params.pop(key, None)
            else:
                params[key] = value
        return "/?" + urlencode(params) if params else "/"

    all_items = [item for col in collections for item in col.get("items", [])]
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
        f'<span>{ESC(name)}</span>',
        '<form method="post" action="/api/public/logout">',
        f'<input type="hidden" name="csrf_token" value="{ESC(csrf)}">',
        '<button class="text-button" type="submit">Déconnexion</button>',
        '</form></div></header>',
        f'<main class="library view-{ESC(view)}">',
        '<header class="library-header"><h1>Bon retour.</h1>',
        '<p class="lede">Reprenez là où votre esprit s\'est arrêté.</p>',
        '<form class="search-form" method="get" action="/">',
        f'<input type="search" name="q" value="{ESC(query)}" '
        'placeholder="Rechercher un livre, un auteur…" aria-label="Rechercher un livre, un auteur">',
        '<button type="submit">Rechercher</button></form>',
        '<div class="controls-block">',
        '<nav class="control-row" aria-label="Mode d\'affichage"><span class="label">Vue</span>',
    ]
    for label, value in (("Liste", "liste"), ("Grille", "grille"), ("Immersif", "immersif")):
        current = "true" if view == value else "false"
        parts.append(
            f'<a class="view-link" href="{ESC(href(vue=value if value != "liste" else None))}" '
            f'aria-current="{current}">{label}</a>'
        )
    parts.append('</nav>')

    if collection_options:
        parts.append('<nav class="control-row" aria-label="Collections"><span class="label">Collections</span>')
        parts.append('<a class="facet" href="#tous" aria-pressed="false">Toute la bibliothèque</a>')
        for copt in collection_options:
            parts.append(
                f'<span class="pill pill-static" title="{ESC(copt["title"])}">'
                f'{ESC(copt["title"])} <small>({copt["count"]})</small></span>'
            )
        parts.append('</nav>')

    if author_options:
        show_limit = 10
        parts.append('<nav class="control-row facets" id="author-facets" aria-label="Filtrer par auteur"><span class="label">Auteurs</span>')
        parts.append(
            f'<a class="facet" data-author="*" href="{ESC(href(auteur=None))}" '
            f'aria-pressed="{"true" if not active_author else "false"}">Tous</a>'
        )
        for idx, author in enumerate(author_options):
            count = author_counts.get(author, 0)
            extra = " facet-extra" if idx >= show_limit else ""
            hidden_attr = ' hidden' if idx >= show_limit else ''
            parts.append(
                f'<a class="facet{extra}" data-author="{ESC(author.lower())}" href="{ESC(href(auteur=author))}" '
                f'aria-pressed="{"true" if active_author == author else "false"}"{hidden_attr}>'
                f'{ESC(author)} <small>({count})</small></a>'
            )
        if len(author_options) > show_limit:
            parts.append(
                '<button type="button" class="text-button facet-toggle" id="authors-toggle" '
                f'data-more="Voir tous les auteurs ({len(author_options)})" data-less="Voir moins">Voir tous les auteurs ({len(author_options)})</button>'
            )
        if active_author or query:
            parts.append(f'<a class="facet-clear" href="{ESC(href(auteur=None, q=None))}">Effacer les filtres</a>')
        parts.append('<div class="facet-tools">')
        parts.append('<input type="search" id="author-search" class="facet-search" placeholder="Rechercher un auteur…" aria-label="Rechercher parmi les auteurs">')
        parts.append('</div></nav>')

    parts.append('</div></header>')

    parts.append(
        '<nav class="discovery" aria-label="Découvrir la bibliothèque">'
        '<a href="#resume">Reprendre l\'écoute</a>'
        '<a href="#nouveautes">Nouveautés</a>'
        '<a href="#decouvrir">À découvrir</a>'
        '<a href="#tous">Toute la bibliothèque</a>'
        '</nav>'
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
        fhue = sum(ord(c) for c in flabel) * 37 % 360
        fcover = featured.get("cover_url") or ""
        fcover_inner = f'<span>{ESC(flabel[:1].upper() or "A")}</span>'
        if fcover:
            fcover_inner += f'<img src="{ESC(fcover)}" alt="" onerror="this.remove()">'
        fmeta = "Prêt à être écouté"
        if fprogress and fduration:
            remaining = max(0.0, fduration - fprogress)
            fmeta = f"{_position_text(fprogress)} écouté · {_position_text(remaining)} restant"
        elif fprogress:
            fmeta = f"Repris à {_position_text(fprogress)}"
        elif fduration:
            fmeta = _duration_text(fduration)
        cta = "Continuer l'écoute" if fprogress > 0 else "Lancer l'écoute"
        parts.extend([
            '<section class="resume-card" aria-label="Reprendre l\'écoute">',
            f'<div class="resume-cover" style="--cover-h:{fhue}">{fcover_inner}</div>',
            '<div class="resume-copy"><p class="eyebrow">Reprendre l\'écoute</p>',
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
        hue = sum(ord(c) for c in label) * 37 % 360
        img = f'<img src="{ESC(cover)}" alt="" onerror="this.remove()">' if cover else ""
        idx = id_to_index.get(str(first.get("id")), 0)
        parts.extend([
            '<section class="hero" aria-label="Lecture immersive">',
            f'<div class="big-cover" style="--cover-h:{hue}" id="immersive-cover-host">',
            f'<span>{ESC(label[:1].upper() or "A")}</span>{img}</div>',
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

    shelf("resume", "Reprendre l'écoute", resume, "Vos lectures en cours, à la dernière position.")
    shelf("nouveautes", "Nouveautés", newest, "Les titres récemment ajoutés à votre bibliothèque.")
    shelf("decouvrir", "À découvrir", discover, "Une sélection pour varier vos prochaines écoutes.")
    for col in collections:
        shelf("tous", col.get("title") or "Bibliothèque", col.get("items", []))

    chapter_map = {
        str(item.get("id")): (item.get("chapters") or [])
        for item in all_items
    }
    chapters_json = json.dumps(chapter_map, ensure_ascii=False).replace("<", "\\u003c")
    parts.append(
        '<script type="application/json" id="chapters-data">' + chapters_json + '</script>'
    )

    parts.extend([
        '<audio id="player" preload="none"></audio>',
        '<section class="player-bar" id="player-bar" hidden aria-label="Lecteur audio">',
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
        '<input class="seek" id="seek" type="range" min="0" max="100" value="0" step="0.1" aria-label="Position dans le livre">',
        '<span class="time end" id="time-total">0:00</span>',
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
        '<input id="volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volume"></div>',
        '<div class="utility-buttons" role="group" aria-label="Panneaux et affichage">',
        '<button type="button" class="pill-button icon-button" id="chapters-toggle" aria-label="Chapitres" aria-controls="chapters-panel" aria-expanded="false" title="Chapitres">Chapitres</button>',
        '<button type="button" class="pill-button icon-button" id="queue-toggle" aria-label="File d’attente" aria-controls="queue-panel" aria-expanded="false" title="File d’attente">File</button>',
        '<button type="button" class="pill-button icon-button" id="fullscreen" aria-label="Agrandir le lecteur" aria-pressed="false" title="Agrandir le lecteur">Agrandir</button>',
        '<button type="button" class="pill-button icon-button" id="close" aria-label="Fermer le lecteur" title="Fermer ou arrêter">Fermer</button>',
        '</div></div>',
        '<p class="player-status" id="player-status" role="status" aria-live="polite"></p>',
        '</section>',

        '<aside class="queue-panel" id="queue-panel" hidden aria-label="File d\'attente">',
        '<div class="queue-panel-head"><h3>Dans la file</h3>'
        '<button type="button" class="icon-button panel-close" data-close-panel="queue-panel" aria-label="Fermer la file" title="Fermer">×</button></div>'
        '<div id="queue-list" class="panel-list"></div></aside>',
        '<aside class="queue-panel" id="chapters-panel" hidden aria-label="Chapitres">',
        '<div class="queue-panel-head"><h3>Chapitres</h3>'
        '<button type="button" class="icon-button panel-close" data-close-panel="chapters-panel" aria-label="Fermer les chapitres" title="Fermer">×</button></div>'
        '<div id="chapters-list" class="panel-list"></div></aside>',

        _PLAYER_JS.replace("__CSRF__", ESC(csrf)),
        '</main></body></html>',
    ])
    return "".join(parts)
