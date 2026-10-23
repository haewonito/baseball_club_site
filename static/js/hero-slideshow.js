// Banner slideshow (home page): cross-fades the .hero-banner__slide images,
// advancing every few seconds, with dots to jump. Stays still for visitors who
// ask for reduced motion, and does nothing with a single picture.
(function () {
  var banner = document.querySelector("[data-hero-slideshow]");
  if (!banner) return;
  var slides = banner.querySelectorAll(".hero-banner__slide");
  var dots = banner.querySelectorAll(".hero-banner__dot");
  if (slides.length < 2) return;

  var current = 0;
  var timer = null;

  function show(index) {
    slides[current].classList.remove("is-active");
    if (dots[current]) dots[current].classList.remove("is-active");
    current = (index + slides.length) % slides.length;
    slides[current].classList.add("is-active");
    if (dots[current]) dots[current].classList.add("is-active");
  }

  function start() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches) return;
    timer = setInterval(function () { show(current + 1); }, 6000);
  }

  dots.forEach(function (dot, index) {
    dot.addEventListener("click", function () {
      clearInterval(timer);
      show(index);
      start();
    });
  });
  start();
})();
