// Shared hover/focus tooltip layer. Any element with data-tip-value (and
// optionally data-tip-label) gets a tooltip; values are inserted with
// textContent only. Keyboard focus shows the same details as hover.
(function () {
  const tip = document.createElement("div");
  tip.className = "viz-tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tip));

  const valueEl = document.createElement("div");
  valueEl.className = "viz-tip-value";
  const labelEl = document.createElement("div");
  labelEl.className = "viz-tip-label";
  tip.append(valueEl, labelEl);

  function fill(el) {
    valueEl.textContent = el.dataset.tipValue || "";
    labelEl.textContent = el.dataset.tipLabel || "";
    labelEl.hidden = !el.dataset.tipLabel;
  }

  function place(x, y) {
    const pad = 12;
    tip.style.left = "0px";
    tip.style.top = "0px";
    const r = tip.getBoundingClientRect();
    let left = x + pad;
    let top = y + pad;
    if (left + r.width > innerWidth - 8) left = x - r.width - pad;
    if (top + r.height > innerHeight - 8) top = y - r.height - pad;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest?.("[data-tip-value]");
    if (!el) {
      tip.hidden = true;
      return;
    }
    fill(el);
    tip.hidden = false;
    place(e.clientX, e.clientY);
  });
  document.addEventListener("pointerleave", () => (tip.hidden = true));

  document.addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip-value]");
    if (!el) return;
    fill(el);
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    place(r.left + r.width / 2, r.top);
  });
  document.addEventListener("focusout", () => (tip.hidden = true));
})();
