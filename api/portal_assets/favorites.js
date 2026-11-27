// Cœur « favori » : <button data-favorite="<id du livre>" aria-pressed="true|false">.
// Mise à jour immédiate ; retour en arrière si le serveur refuse.
(function () {
  function token() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content') || '';
    var bar = document.getElementById('player-bar');
    return (bar && bar.getAttribute('data-csrf')) || '';
  }
  function heartSvg(on) {
    return '<svg class="fav-svg" aria-hidden="true" viewBox="0 0 24 24" fill="'
      + (on ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="1.7" '
      + 'stroke-linecap="round" stroke-linejoin="round"><path d="M12 20.5S4.5 16 4.5 10.3'
      + 'A3.9 3.9 0 0 1 12 8.1a3.9 3.9 0 0 1 7.5 2.2C19.5 16 12 20.5 12 20.5Z"/></svg>';
  }
  function paint(id, on) {
    var buttons = document.querySelectorAll('[data-favorite="' + id + '"]');
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      var icon = b.querySelector('.fav-icon');
      if (icon) icon.innerHTML = heartSvg(on);
      var text = b.querySelector('.fav-text');
      if (text) text.textContent = on ? 'Dans mes favoris' : 'Ajouter aux favoris';
    }
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest && e.target.closest('[data-favorite]');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    var id = b.getAttribute('data-favorite');
    var next = b.getAttribute('aria-pressed') !== 'true';
    paint(id, next);
    fetch('/api/public/favorites/' + encodeURIComponent(id), {
      method: next ? 'PUT' : 'DELETE',
      headers: { 'X-CSRF-Token': token() },
      credentials: 'same-origin'
    }).then(function (r) { if (!r.ok) throw new Error('refused'); })
      .catch(function () { paint(id, !next); });
  }, true);
})();
