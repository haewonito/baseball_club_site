// Django admin, Banner Pictures: drag the picture inside the banner-shaped
// frame to choose which part of it the home page banner keeps. Writes the
// position (0-100 on each axis, like CSS object-position) into the hidden
// focus_x / focus_y inputs. Also previews a newly chosen file before saving.
// Django admin puts Media scripts in the page head, so wait for the form to exist.
document.addEventListener("DOMContentLoaded", function () {
  var frame = document.querySelector("[data-crop-frame]");
  if (!frame) return;
  var img = frame.querySelector("img");
  var xInput = document.getElementById("id_focus_x");
  var yInput = document.getElementById("id_focus_y");
  var fileInput = document.getElementById("id_image");
  if (!img || !xInput || !yInput) return;

  var x = parseFloat(xInput.value);
  var y = parseFloat(yInput.value);
  if (isNaN(x)) x = 50;
  if (isNaN(y)) y = 50;

  function clamp(n) { return Math.max(0, Math.min(100, n)); }

  function apply() {
    img.style.objectPosition = x + "% " + y + "%";
    xInput.value = Math.round(x);
    yInput.value = Math.round(y);
  }

  // How far the picture overhangs the frame on each axis (object-fit: cover).
  function overhang() {
    var nw = img.naturalWidth, nh = img.naturalHeight;
    if (!nw || !nh) return { x: 0, y: 0 };
    var scale = Math.max(frame.clientWidth / nw, frame.clientHeight / nh);
    return { x: nw * scale - frame.clientWidth, y: nh * scale - frame.clientHeight };
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

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      img.src = URL.createObjectURL(file);
      img.style.display = "block";
      x = 50;
      y = 50;
      apply();
    });
  }
});
