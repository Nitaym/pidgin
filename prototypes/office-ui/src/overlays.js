// ─────────────────────────────────────────────────────────────────────────────
// overlays.js — UI chrome: context menus, fire confirm, decoration picker,
// HUD clock, bottom toolbar buttons, and toast notifications.
// ─────────────────────────────────────────────────────────────────────────────

import { actions, getAgent, getDeco, archetype, reset } from "./store.js";
import { DECORATIONS } from "./config.js";
import { openDialogue, closeDialogue, dropHistory, clearHistory } from "./dialogue.js";
import { openHire, openCustomize } from "./editor.js";

const $ = id => document.getElementById(id);

// ── Toast ────────────────────────────────────────────────────────────────────
let toastTimer;
export function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
}

// ── Generic floating menu placement ──────────────────────────────────────────
function place(menu, x, y) {
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  requestAnimationFrame(() => {
    if (x + menu.offsetWidth  > window.innerWidth)  menu.style.left = (x - menu.offsetWidth)  + "px";
    if (y + menu.offsetHeight > window.innerHeight) menu.style.top  = (y - menu.offsetHeight) + "px";
  });
}

// ── Agent context menu ───────────────────────────────────────────────────────
let ctxAgentId = null;
export function openAgentMenu(id, x, y) {
  closeDecoMenu();
  ctxAgentId = id;
  const a = getAgent(id), arc = archetype(a.archetypeId);
  $("ctx-title").textContent = arc.emoji + "  " + a.name.toUpperCase();
  const m = $("ctx"); m.classList.add("open"); place(m, x, y);
}
function closeAgentMenu() { $("ctx").classList.remove("open"); ctxAgentId = null; }

// ── Decoration context menu ──────────────────────────────────────────────────
let ctxDecoId = null;
export function openDecoMenu(id, x, y) {
  closeAgentMenu();
  ctxDecoId = id;
  // "Edit text" only applies to signs.
  const isSign = getDeco(id)?.dtype === "sign";
  $("ctx-deco-edit").style.display = isSign ? "" : "none";
  $("ctx-deco-sep").style.display  = isSign ? "" : "none";
  const m = $("ctx-deco"); m.classList.add("open"); place(m, x, y);
}
function closeDecoMenu() { $("ctx-deco").classList.remove("open"); ctxDecoId = null; }

// ── Fire confirm ─────────────────────────────────────────────────────────────
let pendingFireId = null;
function askFire(id) {
  pendingFireId = id;
  $("fire-name").textContent = getAgent(id)?.name ?? "this agent";
  $("fire-overlay").classList.add("open");
}

// ── Decoration picker ────────────────────────────────────────────────────────
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

function buildDecoPicker() {
  const host = $("deco-picker");
  host.innerHTML = `<div class="dp-head">▶ ADD DECORATION</div>`;
  DECORATIONS.forEach((section, i) => {
    if (i > 0) host.insertAdjacentHTML("beforeend", `<div class="dp-sep"></div>`);
    const sec = document.createElement("div");
    sec.className = "dp-section";
    sec.innerHTML = `<div class="dp-section-title">${section.group}</div>`;
    const grid = document.createElement("div");
    grid.className = "dp-grid";
    section.items.forEach(item => {
      const cell = document.createElement("div");
      cell.className = "dp-item";
      cell.innerHTML = `<div class="di-icon">${item.icon || item.emoji}</div><div class="di-label">${item.label}</div>`;
      cell.addEventListener("click", () => placeDeco(item));
      grid.appendChild(cell);
    });
    sec.appendChild(grid);

    // Custom free-text entry (used by the Signs section) — name a room your way.
    if (section.custom) {
      const row = document.createElement("div");
      row.className = "dp-custom";
      row.innerHTML = `<input type="text" maxlength="22" placeholder="Custom name…" autocomplete="off"><button class="dp-add">+</button>`;
      const input = row.querySelector("input");
      const add = () => {
        const text = input.value.trim();
        if (!text) return;
        spawnDeco({ dtype: "sign", text: esc(text) });
        input.value = "";
        closePicker();
        toast("Sign placed — drag it where you like.");
      };
      row.querySelector(".dp-add").addEventListener("click", add);
      input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
      sec.appendChild(row);
    }

    host.appendChild(sec);
  });
}

// Place a decoration near the center of the floor.
function spawnDeco(extra) {
  const game = $("game").getBoundingClientRect();
  const x = game.width / 2 - 20 + (Math.random() * 60 - 30);
  const y = game.height * 0.45 + (Math.random() * 60 - 30);
  actions.addDecoration({ x, y, ...extra });
}

function placeDeco(item) {
  const { dtype } = item;
  const extra = { dtype };
  if (dtype === "plant") extra.emoji = item.emoji;
  if (dtype === "chair") { extra.color = item.color; extra.back = item.back; }
  if (dtype === "sign")  extra.text = item.text;
  spawnDeco(extra);
  closePicker();
  toast("Decoration placed — drag it where you like.");
}

function togglePicker() { $("deco-picker").classList.toggle("open"); }
function closePicker()  { $("deco-picker").classList.remove("open"); }

// ── Sign text editor (edit an existing sign) ─────────────────────────────────
let editSignId = null;
function openSignEditor(id) {
  const d = getDeco(id);
  if (!d) return;
  editSignId = id;
  // Show current text with line breaks flattened to spaces for editing.
  $("sign-input").value = (d.text || "").replace(/<br\s*\/?>/gi, " ").replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">");
  $("sign-overlay").classList.add("open");
  setTimeout(() => $("sign-input").focus(), 50);
}
function closeSignEditor() { $("sign-overlay").classList.remove("open"); editSignId = null; }
function saveSignEditor() {
  const text = $("sign-input").value.trim();
  if (editSignId != null && text) actions.updateDecoration(editSignId, { text: esc(text) });
  closeSignEditor();
}

// ── HUD clock ────────────────────────────────────────────────────────────────
const DAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
function tick() {
  const n = new Date();
  $("hud-time").textContent = n.toLocaleTimeString("en-US", { hour12:false });
  $("hud-date").textContent = DAYS[n.getDay()] + " " + n.getDate();
}

export function setAgentCount(n) {
  $("hud-agents").textContent = n + " agent" + (n !== 1 ? "s" : "") + " online";
}

// ── Wire everything ──────────────────────────────────────────────────────────
export function initOverlays() {
  buildDecoPicker();
  tick(); setInterval(tick, 1000);

  // agent menu items
  $("ctx-talk").addEventListener("click", () => { if (ctxAgentId) openDialogue(ctxAgentId); closeAgentMenu(); });
  $("ctx-customize").addEventListener("click", () => { if (ctxAgentId) openCustomize(ctxAgentId); closeAgentMenu(); });
  $("ctx-fire").addEventListener("click", () => { if (ctxAgentId) askFire(ctxAgentId); closeAgentMenu(); });

  // deco menu items
  $("ctx-deco-edit").addEventListener("click", () => { if (ctxDecoId) openSignEditor(ctxDecoId); closeDecoMenu(); });
  $("ctx-deco-remove").addEventListener("click", () => { if (ctxDecoId) actions.removeDecoration(ctxDecoId); closeDecoMenu(); });

  // sign text editor
  $("sign-cancel").addEventListener("click", closeSignEditor);
  $("sign-save").addEventListener("click", saveSignEditor);
  $("sign-overlay").addEventListener("click", e => { if (e.target === $("sign-overlay")) closeSignEditor(); });
  $("sign-input").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); saveSignEditor(); } });

  // fire modal
  $("fire-cancel").addEventListener("click", () => { $("fire-overlay").classList.remove("open"); pendingFireId = null; });
  $("fire-confirm").addEventListener("click", () => {
    const name = getAgent(pendingFireId)?.name ?? "Agent";
    closeDialogue();
    dropHistory(pendingFireId);
    actions.removeAgent(pendingFireId);
    pendingFireId = null;
    $("fire-overlay").classList.remove("open");
    toast(`${name} has been let go.`);
  });

  // toolbar buttons
  $("hire-btn").addEventListener("click", openHire);
  $("deco-btn").addEventListener("click", e => { e.stopPropagation(); togglePicker(); });

  // reset
  $("reset-btn").addEventListener("click", () => $("reset-overlay").classList.add("open"));
  $("reset-cancel").addEventListener("click", () => $("reset-overlay").classList.remove("open"));
  $("reset-confirm").addEventListener("click", () => {
    closeDialogue();
    clearHistory();
    reset();
    $("reset-overlay").classList.remove("open");
    toast("Office reset to defaults.");
  });

  // global dismissers
  document.addEventListener("click", e => {
    if (!$("ctx").contains(e.target)) closeAgentMenu();
    if (!$("ctx-deco").contains(e.target)) closeDecoMenu();
    if (!$("deco-picker").contains(e.target) && e.target !== $("deco-btn")) closePicker();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeAgentMenu(); closeDecoMenu(); closePicker(); closeDialogue(); }
  });
}
