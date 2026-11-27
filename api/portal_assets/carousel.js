(function () {
  // Progressive enhancement: the shelves also work with native touch/trackpad
  // scrolling. These buttons add a deterministic step and reflect the edges.
  function buttonsFor(track) {
    var id = track.id;
    if (!id) return [];
    return document.querySelectorAll('[data-carousel="' + id + '"]');
  }
  function update(track) {
    var buttons = buttonsFor(track);
    if (!buttons.length) return;
    // scroll-snap can settle on a 2px padding offset, not exactly 0.
    var edge = 4;
    var atStart = track.scrollLeft <= edge;
    var atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - edge;
    for (var i = 0; i < buttons.length; i++) {
      var direction = buttons[i].getAttribute('data-carousel-direction');
      buttons[i].disabled = direction === 'prev' ? atStart : atEnd;
    }
  }
  function updateAll() {
    var tracks = document.querySelectorAll('.carousel-track');
    for (var i = 0; i < tracks.length; i++) update(tracks[i]);
  }
  document.addEventListener('click', function (event) {
    var button = event.target && event.target.closest
      ? event.target.closest('[data-carousel-direction]')
      : null;
    if (!button || button.disabled) return;
    var track = document.getElementById(button.getAttribute('data-carousel'));
    if (!track) return;
    var card = track.querySelector('li');
    var width = card ? card.getBoundingClientRect().width : 180;
    var gap = parseFloat(getComputedStyle(track).columnGap || getComputedStyle(track).gap || '0') || 0;
    var step = Math.max(120, (width + gap) * 3);
    var direction = button.getAttribute('data-carousel-direction') === 'prev' ? -1 : 1;
    if (track.scrollBy) track.scrollBy({ left: step * direction, behavior: 'smooth' });
    else track.scrollLeft += step * direction;
    window.setTimeout(function () { update(track); }, 450);
  });
  document.addEventListener('scroll', function (event) {
    var track = event.target && event.target.closest ? event.target.closest('.carousel-track') : null;
    if (track) update(track);
  }, true);
  window.addEventListener('resize', updateAll);
  updateAll();
})();
