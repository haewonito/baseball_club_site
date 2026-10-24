// Django's changelist treats a click as a shift-click range select whenever
// its own "shift is held" flag is set, and that flag only updates on
// keydown/keyup. If Shift is released while the window isn't focused (or a
// shortcut swallows the keyup), the flag sticks and one click selects every
// row between the last-ticked row and this one. Before each checkbox click,
// replay the click's real Shift state to Django's listener.
document.addEventListener(
  "pointerdown",
  function (event) {
    if (event.target.classList && event.target.classList.contains("action-select")) {
      document.dispatchEvent(new KeyboardEvent("keyup", { shiftKey: event.shiftKey }));
    }
  },
  true
);
