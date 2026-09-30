// Click-to-sort tables: put data-sortable on a <table> and tabindex="0" on
// its <th>s. A click (or Enter) sorts the body rows by that column, and a
// second click reverses it. Cells sort by their data-sort value when they
// have one (ISO dates, raw amounts), otherwise by their text; a column where
// every value is a number sorts numerically. Delegated, so it keeps working
// on tables that htmx swaps in.
(function () {
  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    return (cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent).trim();
  }

  function sortBy(th) {
    var table = th.closest("table[data-sortable]");
    var body = table.tBodies[0];
    var index = th.cellIndex;
    var ascending = th.getAttribute("aria-sort") !== "ascending";
    var rows = Array.prototype.slice.call(body.rows);
    var values = rows.map(function (row) { return cellValue(row, index); });
    var numeric = values.every(function (v) { return v !== "" && !isNaN(Number(v)); });

    var order = rows.map(function (row, i) { return { row: row, value: values[i] }; });
    order.sort(function (a, b) {
      var result = numeric
        ? Number(a.value) - Number(b.value)
        : a.value.localeCompare(b.value, undefined, { numeric: true, sensitivity: "base" });
      return ascending ? result : -result;
    });
    order.forEach(function (item) { body.appendChild(item.row); });

    Array.prototype.forEach.call(th.parentNode.cells, function (other) {
      other.removeAttribute("aria-sort");
    });
    th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
  }

  document.addEventListener("click", function (event) {
    var th = event.target.closest("table[data-sortable] th");
    if (th) sortBy(th);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    var th = event.target.closest && event.target.closest("table[data-sortable] th");
    if (th) sortBy(th);
  });
})();
