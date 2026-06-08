// ─────────────────────────────────────────────────────────────────────────────
// dialogue.js — bottom chat box (Stardew-style conversation)
// ─────────────────────────────────────────────────────────────────────────────

import { state, actions, getAgent, archetype } from "./store.js";
import { REPLIES } from "./config.js";

const history = {};   // agentId -> [{role, text}]

const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

export function openDialogue(id) {
  const a = getAgent(id); if (!a) return;
  const arc = archetype(a.archetypeId);

  $("dlg-avatar").textContent = arc.emoji;
  $("dlg-avatar").style.background = a.robot.chassis;
  $("dlg-name").textContent = a.name;
  $("dlg-role").textContent = arc.role;

  $("dialogue").classList.add("open");
  $("bottom-btns").classList.add("shifted");
  actions.setActive(id);

  if (!history[id]) history[id] = [{ role:"agent", text: arc.intro }];
  renderMsgs(id);
  setTimeout(() => $("dlg-input").focus(), 50);
}

export function closeDialogue() {
  $("dialogue").classList.remove("open");
  $("bottom-btns").classList.remove("shifted");
  actions.setActive(null);
}

export function dropHistory(id) { delete history[id]; }
export function clearHistory() { for (const k in history) delete history[k]; }

function renderMsgs(id) {
  const c = $("dlg-msgs"); c.innerHTML = "";
  const a = getAgent(id);
  (history[id] || []).forEach(m => {
    const d = document.createElement("div");
    d.className = "dmsg " + m.role;
    const who = m.role === "user" ? "YOU" : (a?.name ?? "?").toUpperCase();
    d.innerHTML = `<span class="who">${who}:</span><span class="txt">${esc(m.text)}</span>`;
    c.appendChild(d);
  });
  c.scrollTop = c.scrollHeight;
}

function addMsg(id, role, text) {
  (history[id] ||= []).push({ role, text });
  if (state.ui.activeAgentId === id) renderMsgs(id);
}

function simulateReply(id) {
  const a = getAgent(id); if (!a) return;
  const arc = archetype(a.archetypeId);
  actions.setStatus(id, "busy");

  if (state.ui.activeAgentId === id) {
    const c = $("dlg-msgs");
    const ind = document.createElement("div");
    ind.className = "type-ind"; ind.id = "type-ind";
    ind.innerHTML = `<div class="type-dot"></div><div class="type-dot"></div><div class="type-dot"></div>`;
    c.appendChild(ind); c.scrollTop = c.scrollHeight;
  }

  setTimeout(() => {
    $("type-ind")?.remove();
    const pool = REPLIES[a.archetypeId] || ["Got it."];
    actions.setStatus(id, "ready");
    addMsg(id, "agent", pool[Math.floor(Math.random() * pool.length)]);
  }, 900 + Math.random() * 1100);
}

function send() {
  const id = state.ui.activeAgentId; if (!id) return;
  const inp = $("dlg-input");
  const text = inp.value.trim(); if (!text) return;
  inp.value = "";
  addMsg(id, "user", text);
  simulateReply(id);
}

export function initDialogue() {
  $("dlg-close").addEventListener("click", closeDialogue);
  $("dlg-send").addEventListener("click", send);
  $("dlg-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
}
