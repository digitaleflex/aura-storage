// Marque-pages (liste dans le panneau « Chapitres ») et reprise depuis un autre appareil.
(function () {
  var audio = document.getElementById('player');
  var bar = document.getElementById('player-bar');
  var list = document.getElementById('bookmarks-list');
  var addButton = document.getElementById('bookmark-add');
  var prompt = document.getElementById('sync-prompt');
  var promptText = document.getElementById('sync-text');
  var promptGo = document.getElementById('sync-go');
  if (!audio || !bar || !list || !addButton) return;
  var csrf = bar.getAttribute('data-csrf') || '';
  var shown = '';       // id du livre dont les marque-pages sont affichés
  var syncTarget = 0;

  function bookId() {
    var t = document.querySelector('.track-button.playing');
    return (t && t.getAttribute('data-object-id')) || '';
  }
  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    var mm = (h ? ('0' + m).slice(-2) : String(m)) + ':' + ('0' + r).slice(-2);
    return h ? h + ':' + mm : mm;
  }
  function api(method, url, body) {
    var opts = { method: method, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      if (!r.ok) { var e = new Error('http ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  }
  function seek(seconds) {
    audio.currentTime = seconds;
    audio.play().catch(function () {});
  }

  function render(items) {
    list.textContent = '';
    if (!items.length) {
      var empty = document.createElement('p');
      empty.className = 'track-author';
      empty.textContent = 'Aucun marque-page sur ce livre.';
      list.appendChild(empty);
      return;
    }
    items.forEach(function (b) {
      var row = document.createElement('div');
      row.className = 'bookmark-row';
      var go = document.createElement('button');
      go.type = 'button';
      go.textContent = fmt(b.position_seconds) + (b.note ? ' · ' + b.note : '');
      go.addEventListener('click', function () { seek(b.position_seconds); });
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'bookmark-del';
      del.setAttribute('aria-label', 'Supprimer le marque-page ' + fmt(b.position_seconds));
      del.textContent = '×';
      del.addEventListener('click', function () {
        api('DELETE', '/api/public/bookmarks/' + encodeURIComponent(b.id)).then(load).catch(function () {});
      });
      row.appendChild(go);
      row.appendChild(del);
      list.appendChild(row);
    });
  }
  function load() {
    var id = bookId();
    addButton.disabled = !id;
    if (!id) return;
    shown = id;
    api('GET', '/api/public/bookmarks?object_id=' + encodeURIComponent(id))
      .then(function (data) { if (bookId() === id) render(data.bookmarks || []); })
      .catch(function () {});
  }

  var noteDialog = document.getElementById('note-dialog');
  var noteField = document.getElementById('note-text');
  var pendingBook = null;
  addButton.addEventListener('click', function () {
    var id = bookId();
    if (!id) return;
    if (noteDialog && typeof noteDialog.showModal === 'function') {
      pendingBook = id;
      if (noteField) noteField.value = '';
      noteDialog.showModal();
      return;
    }
    saveNote(id, '');
  });
  function saveNote(id, note) {
    api('POST', '/api/public/bookmarks', {
      object_id: id, position_seconds: audio.currentTime || 0, note: note.slice(0, 200)
    }).then(load).catch(function (e) {
      var status = document.getElementById('player-status');
      if (status) status.textContent = e.status === 409 ? 'Trop de marque-pages sur ce livre (50 maximum).' : 'Marque-page non enregistré.';
    });
  }
  if (noteDialog) {
    noteDialog.addEventListener('close', function () {
      var id = pendingBook;
      pendingBook = null;
      if (!id || noteDialog.returnValue !== 'confirm') return;
      saveNote(id, noteField ? noteField.value : '');
    });
  }

  // Livre changé : recharger les marque-pages.
  audio.addEventListener('loadstart', function () { setTimeout(function () { if (bookId() !== shown) load(); }, 0); });
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'chapters-toggle') setTimeout(load, 0);
  }, true);

  // Reprise : au retour sur l'onglet, proposer la position la plus avancée (autre appareil).
  function hide() { if (prompt) prompt.hidden = true; }
  function checkSync() {
    var id = bookId();
    if (!id || !audio.paused || !prompt) return hide();
    api('GET', '/api/public/progress?object_id=' + encodeURIComponent(id)).then(function (data) {
      var server = Number(data.position_seconds) || 0;
      if (bookId() === id && audio.paused && server - (audio.currentTime || 0) > 20) {
        syncTarget = server;
        promptText.textContent = 'Vous en étiez à ' + fmt(server) + ' sur un autre appareil.';
        prompt.hidden = false;
      } else { hide(); }
    }).catch(function () {});
  }
  if (promptGo) promptGo.addEventListener('click', function () { hide(); seek(syncTarget); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) checkSync(); });
  window.addEventListener('focus', checkSync);
  audio.addEventListener('play', hide);
  load();
})();
