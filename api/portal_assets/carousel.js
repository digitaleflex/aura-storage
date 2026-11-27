(function () {
  // Progressive enhancement: the shelves also work with native touch/trackpad
  // scrolling. These buttons only add a deterministic step for mouse users.
  document.addEventListener('click', function (event) {
    var button = event.target && event.target.closest
      ? event.target.closest('[data-carousel-direction]')
      : null;
    if (!button) return;
    var track = document.getElementById(button.getAttribute('data-carousel'));
    if (!track) return;
    var card = track.querySelector('li');
    var width = card ? card.getBoundingClientRect().width : 180;
    var gap = parseFloat(getComputedStyle(track).columnGap || getComputedStyle(track).gap || '0') || 0;
    var step = Math.max(120, (width + gap) * 3);
    var direction = button.getAttribute('data-carousel-direction') === 'prev' ? -1 : 1;
    if (track.scrollBy) track.scrollBy({ left: step * direction, behavior: 'smooth' });
    else track.scrollLeft += step * direction;
  });
})();
