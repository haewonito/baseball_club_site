// Protects typed-in input on forms marked data-unsaved-guard:
//  - leaving the page (link, back button, closing the tab) with unsaved
//    input triggers the browser's own "Leave site?" warning (browsers don't
//    allow custom text there);
//  - anything marked data-cancel (a Cancel button or link) asks first, and
//    only when there is something to lose.
// A form counts as unsaved when a named field differs from what the server
// rendered, or when it is showing validation errors (the rejected input is
// then the rendered value, but it has still never been saved).
(function () {
  var leaving = false; // set while deliberately leaving, so no warning fires

  function isDirty(form) {
    if (form.querySelector(".form-field--error, .form-errors")) return true;
    return Array.prototype.some.call(form.elements, function (el) {
      if (!el.name || el.type === "hidden" || el.type === "submit" || el.type === "button") return false;
      if (el.type === "checkbox" || el.type === "radio") return el.checked !== el.defaultChecked;
      if (el.tagName === "SELECT") {
        return Array.prototype.some.call(el.options, function (o) { return o.selected !== o.defaultSelected; });
      }
      return el.value !== el.defaultValue;
    });
  }

  function anyDirty() {
    return Array.prototype.some.call(document.querySelectorAll("form[data-unsaved-guard]"), isDirty);
  }

  window.addEventListener("beforeunload", function (event) {
    if (leaving || !anyDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });

  // A normal (non-htmx) submit leaves the page on purpose. htmx forms stay
  // on the page, so they are judged again after each swap instead.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.matches && form.matches("form[data-unsaved-guard]") && !form.hasAttribute("hx-post")) {
      leaving = true;
    }
  });

  document.addEventListener("click", function (event) {
    var cancel = event.target.closest("[data-cancel]");
    if (!cancel) return;
    if (anyDirty() && !window.confirm("Discard what you have entered? It has not been saved.")) {
      event.preventDefault();
      return;
    }
    leaving = true;
    // A button (no href) cancels by reloading the page fresh from the server.
    if (cancel.tagName === "BUTTON") {
      event.preventDefault();
      window.location.assign(window.location.pathname + window.location.search);
    }
  });

  // Coming back via the back button must not keep the "leaving" flag.
  window.addEventListener("pageshow", function () { leaving = false; });
})();
