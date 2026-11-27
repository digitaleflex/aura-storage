// Lecteur d'extrait : contrôles AURA, sans le chrome natif du navigateur.
// Le fichier complet reste bloqué côté serveur ; ce script ne protège pas
// l'extrait contre l'inspection réseau, il évite seulement le menu « Enregistrer ».
(function () {
  var PLAY = '<svg class="player-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 9 6-9 6V6Z" fill="currentColor" stroke="none"/></svg>';
  var PAUSE = '<svg class="player-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5v14M16 5v14"/></svg>';

  function format(seconds) {
    var total = Math.max(0, Math.floor(seconds || 0));
    var m = Math.floor(total / 60);
    var s = total % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Native extracts stay non-downloadable even if a control is added later.
  var native = document.querySelectorAll('audio[src^="/extrait/"]');
  for (var n = 0; n < native.length; n++) {
    native[n].setAttribute('controlsList', 'nodownload');
    native[n].setAttribute('disablePictureInPicture', '');
    native[n].addEventListener('contextmenu', function (event) { event.preventDefault(); });
  }

  var players = document.querySelectorAll('[data-preview-player]');
  for (var i = 0; i < players.length; i++) {
    (function (root) {
      var audio = root.querySelector('[data-preview-audio]') || root.querySelector('audio');
      var toggle = root.querySelector('[data-preview-toggle]');
      var seek = root.querySelector('[data-preview-seek]');
      var current = root.querySelector('[data-preview-current]');
      var total = root.querySelector('[data-preview-total]');
      if (!audio || !toggle || !seek) return;
      var fallback = parseFloat(audio.getAttribute('data-preview-duration') || '0') || 0;

      function duration() {
        return isFinite(audio.duration) && audio.duration > 0 ? audio.duration : fallback;
      }
      function paint() {
        var d = duration();
        if (total) total.textContent = format(d);
        if (current) current.textContent = format(audio.currentTime);
        var pct = d ? Math.min(100, (audio.currentTime / d) * 100) : 0;
        seek.value = String(pct);
        seek.setAttribute('aria-valuetext', format(audio.currentTime));
      }
      function state(playing) {
        toggle.innerHTML = playing ? PAUSE : PLAY;
        toggle.setAttribute('aria-label', playing ? 'Mettre l’extrait en pause' : 'Lire l’extrait');
        toggle.setAttribute('title', playing ? 'Mettre l’extrait en pause' : 'Lire l’extrait');
      }

      audio.addEventListener('loadedmetadata', paint);
      audio.addEventListener('timeupdate', paint);
      audio.addEventListener('play', function () { state(true); });
      audio.addEventListener('pause', function () { state(false); });
      audio.addEventListener('ended', function () { state(false); seek.value = '0'; });
      toggle.addEventListener('click', function () {
        if (audio.paused) audio.play().catch(function () {});
        else audio.pause();
      });
      seek.addEventListener('input', function () {
        var d = duration();
        if (d) audio.currentTime = (parseFloat(seek.value) || 0) / 100 * d;
      });
      paint();
    })(players[i]);
  }
})();
