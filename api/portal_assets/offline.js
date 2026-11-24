// Écoute hors connexion : le bouton « Télécharger » du lecteur copie le livre en cours
// dans le cache « aura-audio » ; le service worker le sert ensuite sans réseau.
(function () {
  if (!('caches' in window)) return;
  var AUDIO = 'aura-audio';
  var button = document.getElementById('offline-toggle');
  var status = document.getElementById('player-status');
  var done = {};
  var busy = false;

  function path(url) { return new URL(url, window.location.href).pathname; }
  function current() { return document.querySelector('.track-button.playing'); }
  function say(text) { if (status) status.textContent = text; }

  function refresh() {
    return caches.open(AUDIO).then(function (c) { return c.keys(); }).then(function (keys) {
      done = {};
      keys.forEach(function (r) { done[new URL(r.url).pathname] = true; });
      var tracks = document.querySelectorAll('.track-button');
      for (var i = 0; i < tracks.length; i++) {
        var u = tracks[i].getAttribute('data-url');
        if (u && done[path(u)]) tracks[i].setAttribute('data-offline', ''); else tracks[i].removeAttribute('data-offline');
      }
      paint();
    }).catch(function () {});
  }

  function paint() {
    if (!button) return;
    var track = current();
    var url = track && track.getAttribute('data-url');
    button.disabled = !url || busy;
    var have = url && done[path(url)];
    button.setAttribute('aria-pressed', have ? 'true' : 'false');
    button.textContent = busy ? 'Téléchargement…' : (have ? 'Hors ligne ✓' : 'Télécharger');
    button.title = have ? 'Retirer ce livre de cet appareil' : 'Télécharger ce livre pour l’écouter sans connexion';
  }

  async function toggle() {
    var track = current();
    var url = track && track.getAttribute('data-url');
    if (!url || busy) return;
    var key = window.location.origin + path(url);
    var cache = await caches.open(AUDIO);
    if (done[path(url)]) {
      await cache.delete(key);
      say('Livre retiré de cet appareil.');
      return refresh();
    }
    busy = true; paint();
    say('Téléchargement en cours… Gardez cette page ouverte.');
    try {
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist();
      // /m/{slug} is a premium capability served from a public-session cookie.
      var response = await fetch(url, { credentials: 'same-origin' });
      if (!response.ok) throw new Error('http ' + response.status);
      await cache.put(key, response);
      say('Disponible hors connexion : « ' + (track.getAttribute('data-title') || 'livre') + ' ».');
    } catch (err) {
      await cache.delete(key).catch(function () {});
      say(err && err.name === 'QuotaExceededError'
        ? 'Espace insuffisant sur cet appareil.'
        : 'Téléchargement impossible (réseau, ou le stockage n’autorise pas ce site).');
    }
    busy = false;
    refresh();
  }

  if (button) button.addEventListener('click', toggle);
  var audio = document.getElementById('player');
  if (audio) ['loadstart', 'emptied'].forEach(function (n) { audio.addEventListener(n, paint); });
  document.addEventListener('click', function () { setTimeout(paint, 50); }, true);
  refresh();
})();
