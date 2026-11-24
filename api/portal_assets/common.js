// Chargé sur toutes les pages du portail. Remplace les attributs inline
// (onerror, onsubmit) interdits par la Content-Security-Policy.
(function () {
  // Une pochette qui ne charge pas disparaît : la couverture typographique reste.
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (t && t.tagName === 'IMG' && t.hasAttribute('data-fallback')) t.remove();
  }, true);
  // Confirmation avant une action irréversible : <form data-confirm="...">.
  document.addEventListener('submit', function (e) {
    var msg = e.target && e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);
  // Bouton « Copier le lien » : <button data-copy="https://…">.
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest && e.target.closest('[data-copy]');
    if (!b || !navigator.clipboard) return;
    navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function () {
      var old = b.textContent; b.textContent = 'Lien copié ✓';
      setTimeout(function () { b.textContent = old; }, 1800);
    }, function () {});
  });
})();
