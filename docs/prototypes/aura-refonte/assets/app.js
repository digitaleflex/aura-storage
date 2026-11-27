/* AURA prototype — interactions de démonstration, sans backend. */
(function () {
  'use strict';

  // Révélation douce des sections au défilement. La classe est ajoutée par JS :
  // sans JavaScript, tout le contenu reste visible.
  var revealables = document.querySelectorAll(
    '.section, .page-head, .search-section, .cats, .detail-hero, .player-stage > *, .ds-section'
  );
  revealables.forEach(function (el) { el.classList.add('reveal'); });
  var revealAll = new URLSearchParams(location.search).get('reveal') === 'all';
  if (revealAll) revealables.forEach(function (el) { el.classList.add('in'); });
  if (!revealAll && 'IntersectionObserver' in window && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    revealables.forEach(function (el) { observer.observe(el); });
  } else {
    revealables.forEach(function (el) { el.classList.add('in'); });
  }

  // Icône de recherche : atteint le champ de la page courante.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('button[aria-label="Rechercher"]');
    if (!btn) return;
    const input = document.querySelector('input[type="search"]');
    if (input) {
      e.preventDefault();
      input.scrollIntoView({ block: 'center', behavior: 'smooth' });
      input.focus({ preventScroll: true });
    }
  });

  // Menu mobile : panneau léger, refermable.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.head-menu-toggle');
    if (!btn) return;
    e.preventDefault();
    const existing = document.querySelector('.mobile-menu');
    if (existing) { existing.remove(); return; }
    const menu = document.createElement('nav');
    menu.className = 'mobile-menu';
    menu.setAttribute('aria-label', 'Menu mobile');
    menu.innerHTML = [
      '<a href="01-accueil-desktop.html">Accueil</a>',
      '<a href="03-bibliotheque.html">Bibliothèque</a>',
      '<a href="05-lecteur.html">En cours d’écoute</a>',
      '<a href="06-recherche-etats.html">Recherche et filtres</a>',
      '<a href="design-system.html">Système de design</a>'
    ].join('');
    const header = document.querySelector('.site-head');
    if (header) header.after(menu);
  });

  // Favoris : bascule locale, purement visuelle.
  document.addEventListener('click', function (e) {
    const fav = e.target.closest('.fav');
    if (fav) {
      e.preventDefault();
      const on = fav.getAttribute('aria-pressed') === 'true';
      fav.setAttribute('aria-pressed', on ? 'false' : 'true');
      const icon = fav.querySelector('.fav-icon');
      if (icon) icon.textContent = on ? '♡' : '♥';
    }
  });

  // Catégories : une seule sélection active.
  document.addEventListener('click', function (e) {
    const chip = e.target.closest('.cat-chip');
    if (!chip) return;
    e.preventDefault();
    document.querySelectorAll('.cat-chip').forEach(function (c) {
      c.setAttribute('aria-pressed', String(c === chip));
    });
  });

  // Bascule grille / liste.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-view]');
    if (!btn) return;
    const view = btn.getAttribute('data-view');
    document.querySelectorAll('[data-view]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b === btn));
    });
    const grid = document.querySelector('[data-grid]');
    if (grid) grid.classList.toggle('as-list', view === 'liste');
  });

  // Onglets d'états (recherche / filtres) : l'état peut aussi venir de l'URL.
  function activateState(name) {
    const panel = document.getElementById('state-' + name);
    if (!panel) return;
    document.querySelectorAll('.state-tab').forEach(function (t) {
      t.setAttribute('aria-selected', String(t.getAttribute('data-state') === name));
    });
    document.querySelectorAll('.state-panel').forEach(function (p) {
      p.classList.toggle('active', p === panel);
    });
  }
  var params = new URLSearchParams(location.search);
  var initialState = params.get('state');
  if (initialState) activateState(initialState);
  var query = params.get('q');
  if (query) {
    document.querySelectorAll('input[type="search"]').forEach(function (i) { i.value = query; });
    document.querySelectorAll('[data-echo-query]').forEach(function (s) { s.textContent = query; });
  }

  document.addEventListener('click', function (e) {
    const tab = e.target.closest('.state-tab');
    if (!tab) return;
    const name = tab.getAttribute('data-state');
    activateState(name);
    if (history.replaceState) {
      var q = new URLSearchParams(location.search).get('q');
      history.replaceState(null, '', '?state=' + name + (q ? '&q=' + encodeURIComponent(q) : ''));
    }
  });

  // Lecture simulée : met à jour la barre miniature du prototype.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.js-play');
    if (!btn) return;
    const mini = document.querySelector('.mini-player');
    if (!mini) return;
    e.preventDefault();
    const title = btn.getAttribute('data-title') || 'Livre audio';
    const author = btn.getAttribute('data-author') || '';
    const cover = btn.getAttribute('data-cover') || '';
    const t = mini.querySelector('[data-mini-title]');
    const a = mini.querySelector('[data-mini-author]');
    const img = mini.querySelector('[data-mini-cover] img');
    if (t) t.textContent = title;
    if (a) a.textContent = author;
    if (img && cover) img.setAttribute('src', cover);
    mini.hidden = false;
    const play = mini.querySelector('.js-mini-play');
    if (play) play.setAttribute('aria-label', 'Mettre en pause');
  });

  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.js-mini-play');
    if (!btn) return;
    const playing = btn.getAttribute('aria-label') === 'Mettre en pause';
    btn.setAttribute('aria-label', playing ? 'Reprendre la lecture' : 'Mettre en pause');
  });

  // Réinitialisation visuelle des filtres.
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.js-reset');
    if (!btn) return;
    e.preventDefault();
    document.querySelectorAll('.filter-pill').forEach(function (p) { p.remove(); });
    document.querySelectorAll('.cat-chip').forEach(function (c, i) {
      c.setAttribute('aria-pressed', String(i === 0));
    });
  });
})();
