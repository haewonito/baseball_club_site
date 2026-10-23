// Django admin, Banner Pictures: drag the picture inside the banner-shaped
// frame, and zoom with the slider, to choose which part the home page banner
// keeps. Writes the position (0-100 on each axis, like CSS object-position) and
// the zoom (100-300 percent) into the hidden focus_x / focus_y / zoom inputs.
// Also previews a newly chosen file before saving. The display rule matches
// templates/home.html: object-position and transform-origin share the same
// point, so zooming keeps that point fixed and the picture never stretches.
// Django admin puts Media scripts in the page head, so wait for the form to exist.
document.addEventListener("DOMContentLoaded", function () {
  var frame = document.querySelector("[data-crop-frame]");
  if (!frame) return;
  var img = frame.querySelector("img");
  var xInput = document.getElementById("id_focus_x");
  var yInput = document.getElementById("id_focus_y");
  var zoomInput = document.getElementById("id_zoom");
  var slider = document.querySelector("[data-crop-zoom]");
  var fileInput = document.getElementById("id_image");
  if (!img || !xInput || !yInput || !zoomInput) return;

  var x = parseFloat(xInput.value);
  var y = parseFloat(yInput.value);
  var zoom = parseFloat(zoomInput.value);
  if (isNaN(x)) x = 50;
  if (isNaN(y)) y = 50;
  if (isNaN(zoom)) zoom = 100;

  function clamp(n) { return Math.max(0, Math.min(100, n)); }

  function apply() {
    img.style.objectPosition = x + "% " + y + "%";
    img.style.transformOrigin = x + "% " + y + "%";
    img.style.transform = "scale(" + zoom / 100 + ")";
    xInput.value = Math.round(x);
    yInput.value = Math.round(y);
    zoomInput.value = Math.round(zoom);
    if (slider) slider.value = zoom;
  }

  // How far the (zoomed) picture overhangs the frame on each axis.
  function overhang() {
    var nw = img.naturalWidth, nh = img.naturalHeight;
    if (!nw || !nh) return { x: 0, y: 0 };
    var fw = frame.clientWidth, fh = frame.clientHeight;
    var scale = Math.max(fw / nw, fh / nh) * (zoom / 100);
    return { x: nw * scale - fw, y: nh * scale - fh };
  }

  var drag = null;

  frame.addEventListener("pointerdown", function (event) {
    drag = { px: event.clientX, py: event.clientY, x: x, y: y };
    frame.setPointerCapture(event.pointerId);
    frame.style.cursor = "grabbing";
  });

  frame.addEventListener("pointermove", function (event) {
    if (!drag) return;
    var o = overhang();
    // Dragging the picture right/down reveals its left/top, so the position falls.
    if (o.x > 1) x = clamp(drag.x - ((event.clientX - drag.px) / o.x) * 100);
    if (o.y > 1) y = clamp(drag.y - ((event.clientY - drag.py) / o.y) * 100);
    apply();
  });

  function endDrag() {
    drag = null;
    frame.style.cursor = "grab";
  }
  frame.addEventListener("pointerup", endDrag);
  frame.addEventListener("pointercancel", endDrag);

  if (slider) {
    slider.addEventListener("input", function () {
      zoom = parseFloat(slider.value);
      apply();
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      img.src = URL.createObjectURL(file);
      img.style.display = "block";
      x = 50;
      y = 50;
      zoom = 100;
      apply();
    });
  }
});
