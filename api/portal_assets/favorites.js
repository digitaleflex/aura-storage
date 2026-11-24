// Cœur « favori » : <button data-favorite="<id du livre>" aria-pressed="true|false">.
// Mise à jour immédiate ; retour en arrière si le serveur refuse.
(function () {
  function token() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content') || '';
    var bar = document.getElementById('player-bar');
    return (bar && bar.getAttribute('data-csrf')) || '';
  }
  function paint(id, on) {
    var buttons = document.querySelectorAll('[data-favorite="' + id + '"]');
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      var icon = b.querySelector('.fav-icon');
      if (icon) icon.textContent = on ? '♥' : '♡';
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
