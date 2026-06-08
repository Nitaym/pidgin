// ─────────────────────────────────────────────────────────────────────────────
// drag.js — GENERIC DRAG CONTROLLER
// Works for any entity that has {x, y}. The component supplies the DOM element
// as a drag handle; we move it live and commit positions back to the entity.
// `shouldCancelClick()` lets click handlers ignore the click that ends a drag.
// ─────────────────────────────────────────────────────────────────────────────

import { DESK_W, FLOOR_TOP } from "./config.js";

export function createDnd({ bounds, onEnd }) {
  let cur = null, moved = false, cancelClick = false;

  // el = the element to move (left/top); ent = the {x,y} entity to mutate.
  function begin(ent, el, e) {
    if (e.button !== 0) return;
    e.stopPropagation();
    cur = { ent, el, ox: e.clientX - ent.x, oy: e.clientY - ent.y };
    moved = false;
    el.classList.add("dragging");
    document.body.style.cursor = "grabbing";
  }

  window.addEventListener("mousemove", e => {
    if (!cur) return;
    moved = true;
    const b = bounds();
    cur.ent.x = Math.max(0, Math.min(e.clientX - cur.ox, b.w - DESK_W));
    cur.ent.y = Math.max(FLOOR_TOP, Math.min(e.clientY - cur.oy, b.h - 110));
    cur.el.style.left = cur.ent.x + "px";
    cur.el.style.top  = cur.ent.y + "px";
  });

  window.addEventListener("mouseup", () => {
    if (!cur) return;
    cur.el.classList.remove("dragging");
    document.body.style.cursor = "";
    cancelClick = moved;
    cur = null;
    if (moved && onEnd) onEnd();
  });

  return {
    begin,
    shouldCancelClick() { const c = cancelClick; cancelClick = false; return c; },
  };
}
