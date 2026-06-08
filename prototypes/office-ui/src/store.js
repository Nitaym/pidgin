// ─────────────────────────────────────────────────────────────────────────────
// store.js — SINGLE SOURCE OF TRUTH (persisted to the Python backend)
// State is only ever mutated through `actions`, which emit afterwards so
// subscribed views re-render. Every emit schedules a debounced save to the
// backend's JSON store (PUT /api/office).
// ─────────────────────────────────────────────────────────────────────────────

import { AGENT_ARCHETYPES, NAME_POOL } from "./config.js";
import { loadOffice, saveOffice } from "./api.js";

// ── State ────────────────────────────────────────────────────────────────────
export const state = {
  agents: [],
  decorations: [],
  ui: { activeAgentId: null },
  _seq: 1,
};

// ── Pub/Sub ──────────────────────────────────────────────────────────────────
const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { listeners.forEach(fn => fn(state)); save(); }

// ── Persistence (debounced PUT to backend) ───────────────────────────────────
let saveTimer = null;
export function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveOffice({ agents: state.agents, decorations: state.decorations, _seq: state._seq })
      .catch(err => console.warn("[pidgin] save failed:", err.message));
  }, 250);
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function nextId() { return state._seq++; }
export function archetype(id) { return AGENT_ARCHETYPES.find(a => a.id === id); }
export function getAgent(id)  { return state.agents.find(a => a.id === id); }
export function getDeco(id)   { return state.decorations.find(d => d.id === id); }

export function suggestName() {
  const used = state.agents.map(a => a.name);
  return NAME_POOL.find(n => !used.includes(n)) || ("Bot-" + state._seq);
}

// ── Actions (the only mutators) ──────────────────────────────────────────────
export const actions = {
  addAgent({ archetypeId, name, robot, x, y }) {
    const arc = archetype(archetypeId);
    const id = nextId();
    state.agents.push({
      id, archetypeId,
      name: name || suggestName(),
      robot: robot || { ...arc.robot },
      x: x ?? 80, y: y ?? 265,
      status: "ready",
    });
    emit();
    return id;
  },

  removeAgent(id) {
    state.agents = state.agents.filter(a => a.id !== id);
    if (state.ui.activeAgentId === id) state.ui.activeAgentId = null;
    emit();
  },

  updateAgent(id, patch) {
    const a = getAgent(id);
    if (!a) return;
    Object.assign(a, patch);
    emit();
  },

  setStatus(id, status) {
    const a = getAgent(id);
    if (a) { a.status = status; emit(); }
  },

  setActive(id) { state.ui.activeAgentId = id; emit(); },

  addDecoration(deco) { state.decorations.push({ id: nextId(), ...deco }); emit(); },
  updateDecoration(id, patch) { const d = getDeco(id); if (d) { Object.assign(d, patch); emit(); } },
  removeDecoration(id) { state.decorations = state.decorations.filter(d => d.id !== id); emit(); },
};

// ── Lifecycle ────────────────────────────────────────────────────────────────
// Fetch the saved office from the backend, or seed a fresh one. Async because
// it hits the network.
export async function init() {
  try {
    const data = await loadOffice();
    const hasData = !data.empty && ((data.agents && data.agents.length) || (data.decorations && data.decorations.length));
    if (hasData) {
      state.agents = (data.agents || []).map(a => ({
        ...a,
        status: a.status === "busy" ? "ready" : a.status,   // never restore mid-reply
      }));
      state.decorations = data.decorations || [];
      state._seq = data._seq || 1;
      return;
    }
  } catch (err) {
    console.warn("[pidgin] backend unavailable, starting fresh:", err.message);
  }
  seed();
}

export function reset() {
  state.agents = [];
  state.decorations = [];
  state.ui.activeAgentId = null;
  state._seq = 1;
  seed();   // emits -> saves the fresh office to the backend
}

function seed() {
  actions.addAgent({ archetypeId:"researcher", name:"Alex",   x:60,  y:265 });
  actions.addAgent({ archetypeId:"engineer",   name:"Morgan", x:430, y:305 });
  actions.addAgent({ archetypeId:"writer",     name:"Jordan", x:800, y:265 });
  const morgan = state.agents.find(a => a.name === "Morgan");
  if (morgan) { morgan.status = "idle"; emit(); }
}
