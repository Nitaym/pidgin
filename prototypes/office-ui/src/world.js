// ─────────────────────────────────────────────────────────────────────────────
// world.js — renders agents (desks) + decorations into #objects.
// Subscribes to the store and re-renders on any change. Entities are depth-
// sorted by Y so closer objects overlap farther ones.
// ─────────────────────────────────────────────────────────────────────────────

import { state, getAgent, getDeco, archetype, save } from "./store.js";
import { DESK_W, DEFAULT_DESK } from "./config.js";
import { buildRobot, shade } from "./robot.js";
import { createDnd } from "./drag.js";
import { openDialogue } from "./dialogue.js";
import { openAgentMenu, openDecoMenu, setAgentCount } from "./overlays.js";

let dnd;

function bounds() {
  const r = document.getElementById("game").getBoundingClientRect();
  return { w: r.width, h: r.height };
}

// ── Desk props (per job) ─────────────────────────────────────────────────────
function monitorInner(v) {
  switch (v) {
    case "code":   return `<div class="scr-lines code"><i></i><i></i><i></i></div>`;
    case "text":   return `<div class="scr-lines text"><i></i><i></i><i></i></div>`;
    case "chart":  return `<div class="scr-bars"><i></i><i></i><i></i><i></i></div>`;
    case "search": return `<span class="scr-emoji">🔍</span>`;
    default:       return `<span class="scr-cursor">▮</span>`;
  }
}
function deskItem(it, status) {
  switch (it.t) {
    case "monitor":  return `<div class="dmonitor${status === "ready" ? " on" : ""}">${monitorInner(it.v)}</div>`;
    case "mug":      return `<div class="dmug"></div>`;
    case "papers":   return `<div class="dpaper"></div>`;
    case "books":    return `<div class="dbooks"><i style="background:#8b3030"></i><i style="background:#2a6a9a"></i><i style="background:#caa030"></i></div>`;
    case "stickies": return `<div class="dstickies"><i style="background:#ffd24a"></i><i style="background:#ff7a9a"></i><i style="background:#7adcff"></i></div>`;
    case "prop":     return `<div class="desk-prop">${it.e}</div>`;
    default:         return "";
  }
}

// ── Desk (agent) ─────────────────────────────────────────────────────────────
function buildDesk(a) {
  const arc = archetype(a.archetypeId);
  const desk = arc?.desk || DEFAULT_DESK;
  const face = shade(desk.tint, -46);
  const el = document.createElement("div");
  el.className = "desk-w" + (state.ui.activeAgentId === a.id ? " active" : "");
  el.style.left = a.x + "px";
  el.style.top = a.y + "px";
  el.dataset.id = a.id;
  el.innerHTML = `
    <div class="dtop" style="background:${desk.tint};border-color:${shade(desk.tint, -52)}">
      ${desk.items.map(it => deskItem(it, a.status)).join("")}
    </div>
    <div class="dface" style="background:${face};border-color:${shade(face, -28)}"></div>`;

  // sprite wrapper (sits on top of the desk)
  const spr = document.createElement("div");
  spr.className = "agent-spr";
  spr.appendChild(buildRobot(a.robot, a.status));
  const nm = document.createElement("div");
  nm.className = "spr-name";
  nm.textContent = a.name;
  spr.appendChild(nm);
  el.insertBefore(spr, el.firstChild);

  el.addEventListener("click", () => { if (!dnd.shouldCancelClick()) openDialogue(a.id); });
  el.addEventListener("contextmenu", e => { e.preventDefault(); openAgentMenu(a.id, e.clientX, e.clientY); });
  el.querySelector(".dtop").addEventListener("mousedown", e => dnd.begin(a, el, e));
  return el;
}

// ── Decoration ───────────────────────────────────────────────────────────────
function buildDeco(d) {
  const el = document.createElement("div");
  el.className = "game-deco deco-" + d.dtype;
  el.style.left = d.x + "px";
  el.style.top = d.y + "px";
  el.dataset.id = d.id;

  if (d.dtype === "plant") {
    el.innerHTML = `<div class="dp-emoji">${d.emoji}</div><div class="dp-pot"></div>`;
  } else if (d.dtype === "chair") {
    el.innerHTML = `
      <div class="chair-back" style="background:${d.back}"></div>
      <div class="chair-seat" style="background:${d.color};border-color:${d.back}"></div>
      <div class="chair-legs"><div class="chair-leg"></div><div class="chair-leg"></div></div>`;
  } else if (d.dtype === "sign") {
    el.innerHTML = `<div class="sign-board">${d.text}</div><div class="sign-post"></div>`;
  }

  el.addEventListener("mousedown", e => dnd.begin(d, el, e));
  el.addEventListener("contextmenu", e => { e.preventDefault(); openDecoMenu(d.id, e.clientX, e.clientY); });
  return el;
}

// ── Render ───────────────────────────────────────────────────────────────────
export function renderWorld() {
  const host = document.getElementById("objects");
  host.innerHTML = "";

  const items = [
    ...state.agents.map(a => ({ y: a.y + 100, build: () => buildDesk(a) })),
    ...state.decorations.map(d => ({ y: d.y, build: () => buildDeco(d) })),
  ].sort((p, q) => p.y - q.y);

  items.forEach((item, i) => {
    const el = item.build();
    el.style.zIndex = i + 2;
    host.appendChild(el);
  });

  setAgentCount(state.agents.filter(a => a.status !== "offline").length);
}

export function initWorld() {
  // After a drag, persist the new position then re-render (for depth re-sort).
  dnd = createDnd({ bounds, onEnd: () => { save(); renderWorld(); } });
  renderWorld();
}
