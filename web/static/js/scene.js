// Pointer parallax for .scene and .lp-card tilt, plus scroll reveal. The
// motion itself is CSS (static/css/landing.css); this only feeds it numbers.
(function () {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.querySelectorAll('.reveal').forEach(function (el) { el.classList.add('in'); });
    return;
  }
  document.addEventListener('pointermove', function (e) {
    var x = e.clientX / window.innerWidth - 0.5, y = e.clientY / window.innerHeight - 0.5;
    document.querySelectorAll('.scene-tilt').forEach(function (el) {
      el.style.setProperty('--rx', x.toFixed(3));
      el.style.setProperty('--ry', y.toFixed(3));
    });
  });
  document.querySelectorAll('.lp-card').forEach(function (card) {
    card.addEventListener('pointermove', function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--tx', ((e.clientX - r.left) / r.width - 0.5) * 12 + 'deg');
      card.style.setProperty('--ty', ((e.clientY - r.top) / r.height - 0.5) * -12 + 'deg');
    });
    card.addEventListener('pointerleave', function () {
      card.style.setProperty('--tx', '0deg');
      card.style.setProperty('--ty', '0deg');
    });
  });
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } });
  }, { threshold: 0.15 });
  document.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });
})();
