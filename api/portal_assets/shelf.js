(function () {
  // Progressive pagination: reveal shelf items in batches for long lists.
  var BATCH = 12;
  function setupShelf(ul) {
    var items = Array.prototype.slice.call(ul.children || []);
    if (items.length <= BATCH) return;
    var shown = BATCH;
    for (var i = shown; i < items.length; i++) items[i].hidden = true;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pill-button';
    btn.textContent = 'Afficher plus (' + (items.length - shown) + ')';
    btn.style.margin = '1rem auto 0';
    btn.style.display = 'block';
    function revealMore() {
      var next = Math.min(shown + BATCH, items.length);
      for (var j = shown; j < next; j++) items[j].hidden = false;
      shown = next;
      var remaining = items.length - shown;
      if (remaining <= 0) { btn.remove(); observer.disconnect(); return; }
      btn.textContent = 'Afficher plus (' + remaining + ')';
    }
    btn.addEventListener('click', revealMore);
    ul.parentNode.insertBefore(btn, ul.nextSibling);
    var observer = ('IntersectionObserver' in window)
      ? new IntersectionObserver(function (entries) {
          if (entries[0] && entries[0].isIntersecting) revealMore();
        }, { rootMargin: '200px 0px' })
      : null;
    if (observer) observer.observe(btn);
  }
  document.querySelectorAll('.shelf > ul').forEach(setupShelf);

  // Intelligent preload: when a track is active, prefetch next track metadata.
  var prefetchAudio = document.createElement('audio');
  prefetchAudio.preload = 'metadata';
  prefetchAudio.style.display = 'none';
  prefetchAudio.setAttribute('aria-hidden', 'true');
  document.body.appendChild(prefetchAudio);
  var lastPrefetch = '';
  function prefetchNext() {
    var tracks = Array.prototype.slice.call(document.querySelectorAll('[data-url]'));
    var active = document.querySelector('[data-url].playing,[data-url][aria-current="true"]');
    var idx = tracks.indexOf(active);
    if (idx < 0 || idx + 1 >= tracks.length) return;
    var nextUrl = tracks[idx + 1].getAttribute('data-url');
    if (!nextUrl || nextUrl === lastPrefetch) return;
    lastPrefetch = nextUrl;
    prefetchAudio.src = nextUrl;
    prefetchAudio.load();
  }
  var player = document.getElementById('player');
  if (player) {
    ['play', 'loadedmetadata', 'ended'].forEach(function (evt) {
      player.addEventListener(evt, function () { setTimeout(prefetchNext, 300); });
    });
  }
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('[data-url]')) setTimeout(prefetchNext, 500);
  }, true);
})();
