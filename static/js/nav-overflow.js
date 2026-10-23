// Header menu on one line: whatever doesn't fit moves into a "More" dropdown
// (opens on hover, keyboard focus, or tap). Re-measured on resize. Without
// JavaScript the menu just wraps onto several lines (see .site-nav in main.css).
(function () {
  var nav = document.querySelector(".site-nav");
  if (!nav) return;

  var items = Array.prototype.slice.call(nav.children);
  var more = document.createElement("div");
  more.className = "site-nav__more";
  more.hidden = true;
  more.innerHTML =
    '<button type="button" class="site-nav__more-button" aria-haspopup="true" aria-expanded="false">More <span aria-hidden="true">&#9662;</span></button>' +
    '<div class="site-nav__menu"></div>';
  var button = more.querySelector("button");
  var menu = more.querySelector(".site-nav__menu");
  nav.appendChild(more);
  nav.classList.add("site-nav--collapsible");

  function layout() {
    // Everything back in the row, in order, before measuring.
    items.forEach(function (item) { nav.insertBefore(item, more); });
    more.hidden = true;
    more.classList.remove("is-open");
    button.setAttribute("aria-expanded", "false");

    var gap = parseFloat(getComputedStyle(nav).columnGap) || 0;
    var widths = items.map(function (item) { return item.offsetWidth; });
    var total = widths.reduce(function (a, b) { return a + b; }, 0) + gap * (items.length - 1);
    if (total <= nav.clientWidth) return;

    more.hidden = false;
    var room = nav.clientWidth - more.offsetWidth - gap;
    var used = 0;
    var keep = 0;
    while (keep < items.length && used + widths[keep] + gap <= room) {
      used += widths[keep] + gap;
      keep += 1;
    }
    items.slice(keep).forEach(function (item) { menu.appendChild(item); });
  }

  button.addEventListener("click", function () {
    var open = more.classList.toggle("is-open");
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) button.blur(); // else :focus-within would keep the menu showing
  });
  document.addEventListener("click", function (event) {
    if (!more.contains(event.target)) more.classList.remove("is-open");
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") more.classList.remove("is-open");
  });

  var timer = null;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(layout, 80);
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  layout();
})();
