// Ajout d'un livre à une liste de lecture depuis le catalogue (dialogue natif).
(function () {
  var dialog = document.getElementById('playlist-dialog');
  var list = document.getElementById('playlist-dialog-list');
  var status = document.getElementById('playlist-dialog-status');
  var bookLabel = document.getElementById('playlist-dialog-book');
  var closeBtn = document.getElementById('playlist-dialog-close');
  var createForm = document.getElementById('playlist-create-form');
  var createName = document.getElementById('playlist-create-name');
  if (!dialog || !list || !createForm) return;

  var currentObjectId = '';
  var trigger = null;

  function token() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content') || '';
    var bar = document.getElementById('player-bar');
    return (bar && bar.getAttribute('data-csrf')) || '';
  }

  function setStatus(message, isError) {
    if (!status) return;
    status.textContent = message || '';
    status.className = 'playlist-dialog-status' + (isError ? ' is-error' : '');
  }

  function api(method, url, body) {
    var opts = {
      method: method,
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': token() }
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!r.ok) {
          var err = new Error((data && data.detail) || ('http ' + r.status));
          err.status = r.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function renderPlaylists(items) {
    list.textContent = '';
    if (!items || !items.length) {
      var empty = document.createElement('p');
      empty.className = 'track-author';
      empty.textContent = 'Aucune liste pour l’instant. Créez-en une ci-dessous.';
      list.appendChild(empty);
      return;
    }
    items.forEach(function (p) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'playlist-pick';
      btn.setAttribute('data-playlist-id', p.id);
      var name = document.createElement('span');
      name.className = 'playlist-pick-name';
      name.textContent = p.name || 'Liste';
      var state = document.createElement('span');
      state.className = 'playlist-pick-state';
      state.textContent = p.item_count ? (p.item_count + ' titre' + (p.item_count > 1 ? 's' : '')) : '';
      btn.appendChild(name);
      btn.appendChild(state);
      btn.addEventListener('click', function () { addToPlaylist(p.id, btn, state); });
      list.appendChild(btn);
    });
  }

  function loadPlaylists() {
    setStatus('Chargement des listes…');
    return api('GET', '/api/public/playlists').then(function (data) {
      renderPlaylists((data && data.playlists) || []);
      setStatus('');
    }).catch(function (e) {
      renderPlaylists([]);
      setStatus('Impossible de charger les listes.', true);
      if (window.console && console.error) console.error(e);
    });
  }

  function addToPlaylist(playlistId, btn, stateEl) {
    if (!currentObjectId || !playlistId) return;
    btn.disabled = true;
    setStatus('Ajout en cours…');
    api('PUT', '/api/public/playlists/' + encodeURIComponent(playlistId) + '/items/' + encodeURIComponent(currentObjectId))
      .then(function (data) {
        var added = !!(data && data.added);
        btn.classList.add('is-added');
        stateEl.textContent = added ? 'Ajouté' : 'Déjà présent';
        setStatus(added ? 'Livre ajouté à la liste.' : 'Ce livre est déjà dans cette liste.');
      })
      .catch(function (e) {
        btn.disabled = false;
        setStatus('Impossible d’ajouter ce livre à la liste.', true);
        if (window.console && console.error) console.error(e);
      });
  }

  function openDialog(objectId, title, triggerEl) {
    currentObjectId = objectId || '';
    trigger = triggerEl || document.activeElement;
    if (bookLabel) bookLabel.textContent = title ? ('Livre : ' + title) : '';
    setStatus('');
    renderPlaylists([]);
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    loadPlaylists();
  }

  function closeDialog() {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest && e.target.closest('[data-add-playlist]');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    var id = btn.getAttribute('data-add-playlist') || '';
    var card = btn.closest('li');
    var titleEl = card && card.querySelector('.track-title');
    var title = (titleEl && titleEl.textContent) || btn.getAttribute('aria-label') || 'Livre';
    openDialog(id, title, btn);
  }, true);

  if (closeBtn) closeBtn.addEventListener('click', closeDialog);

  dialog.addEventListener('close', function () {
    setStatus('');
    if (trigger && typeof trigger.focus === 'function') {
      trigger.focus();
    }
  });

  dialog.addEventListener('click', function (e) {
    if (e.target === dialog) closeDialog();
  });

  createForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var name = createName ? createName.value.trim() : '';
    if (!name) return;
    var submit = createForm.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    setStatus('Création de la liste…');
    api('POST', '/api/public/playlists', { name: name })
      .then(function () {
        if (createName) createName.value = '';
        return loadPlaylists();
      })
      .catch(function (e) {
        setStatus('Impossible de créer la liste.', true);
        if (window.console && console.error) console.error(e);
      })
      .then(function () {
        if (submit) submit.disabled = false;
        if (createName) createName.focus();
      });
  });
})();
