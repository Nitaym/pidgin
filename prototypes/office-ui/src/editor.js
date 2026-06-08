// ─────────────────────────────────────────────────────────────────────────────
// editor.js — ROBOT BUILDER / CUSTOMIZER
// One modal serves two modes:
//   mode "hire" — pick archetype + customize, then hire a new agent
//   mode "edit" — customize an existing agent's robot (and rename)
// The control rows are generated from ROBOT_PARTS so adding parts needs no code.
// ─────────────────────────────────────────────────────────────────────────────

import { AGENT_ARCHETYPES, ROBOT_PARTS } from "./config.js";
import { actions, getAgent, archetype, suggestName } from "./store.js";
import { buildRobot } from "./robot.js";
import { toast } from "./overlays.js";

const $ = id => document.getElementById(id);

let draft = null;   // { mode, agentId, archetypeId, name, robot }

function defaultRobot(archetypeId) {
  return { ...archetype(archetypeId).robot };
}

export function openHire() {
  const archetypeId = AGENT_ARCHETYPES[0].id;
  draft = { mode:"hire", agentId:null, archetypeId, name: suggestName(), robot: defaultRobot(archetypeId) };
  buildModal();
}

export function openCustomize(agentId) {
  const a = getAgent(agentId); if (!a) return;
  draft = { mode:"edit", agentId, archetypeId: a.archetypeId, name: a.name, robot: { ...a.robot } };
  buildModal();
}

function close() { $("editor-overlay")?.classList.remove("open"); }

function buildModal() {
  let overlay = $("editor-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "editor-overlay";
    overlay.className = "overlay";
    document.body.appendChild(overlay);
    overlay.addEventListener("click", e => { if (e.target === overlay) close(); });
  }
  const isHire = draft.mode === "hire";

  overlay.innerHTML = `
    <div class="modal editor-modal">
      <h2>▶ ${isHire ? "BUILD YOUR ROBOT" : "CUSTOMIZE"}</h2>
      <div class="editor-grid">
        <div class="editor-preview">
          <div class="preview-stage" id="preview-stage"></div>
          <input id="editor-name" class="editor-name" value="${draft.name}" maxlength="14" />
        </div>
        <div class="editor-controls" id="editor-controls"></div>
      </div>
      <div class="mactions">
        <button class="btn btn-ghost" id="editor-cancel">Cancel</button>
        <button class="btn btn-grn"   id="editor-confirm">${isHire ? "Hire" : "Save"}</button>
      </div>
    </div>`;

  buildControls(isHire);
  refreshPreview();
  overlay.classList.add("open");

  $("editor-name").addEventListener("input", e => { draft.name = e.target.value; });
  $("editor-cancel").addEventListener("click", close);
  $("editor-confirm").addEventListener("click", commit);
}

function buildControls(isHire) {
  const host = $("editor-controls");
  host.innerHTML = "";

  // Archetype row (only when hiring)
  if (isHire) {
    const row = document.createElement("div");
    row.className = "ctrl-row";
    row.innerHTML = `<div class="ctrl-label">Role</div>`;
    const chips = document.createElement("div");
    chips.className = "chip-grid";
    AGENT_ARCHETYPES.forEach(arc => {
      const chip = document.createElement("button");
      chip.className = "chip" + (arc.id === draft.archetypeId ? " sel" : "");
      chip.innerHTML = `${arc.emoji} ${arc.label}`;
      chip.addEventListener("click", () => {
        draft.archetypeId = arc.id;
        draft.robot = defaultRobot(arc.id);   // adopt the role's default look
        buildControls(isHire);
        refreshPreview();
      });
      chips.appendChild(chip);
    });
    row.appendChild(chips);
    host.appendChild(row);
  }

  // Color rows (swatches)
  ROBOT_PARTS.colors.forEach(({ key, label, options }) => {
    const row = document.createElement("div");
    row.className = "ctrl-row";
    row.innerHTML = `<div class="ctrl-label">${label}</div>`;
    const grid = document.createElement("div");
    grid.className = "swatch-grid";
    options.forEach(color => {
      const sw = document.createElement("button");
      sw.className = "swatch" + (draft.robot[key] === color ? " sel" : "");
      sw.style.background = color;
      sw.addEventListener("click", () => { draft.robot[key] = color; buildControls(isHire); refreshPreview(); });
      grid.appendChild(sw);
    });
    row.appendChild(grid);
    host.appendChild(row);
  });

  // Pick rows (labelled chips)
  ROBOT_PARTS.picks.forEach(({ key, label, options }) => {
    const row = document.createElement("div");
    row.className = "ctrl-row";
    row.innerHTML = `<div class="ctrl-label">${label}</div>`;
    const grid = document.createElement("div");
    grid.className = "chip-grid";
    options.forEach(opt => {
      const chip = document.createElement("button");
      chip.className = "chip" + (draft.robot[key] === opt.id ? " sel" : "");
      chip.textContent = opt.label;
      chip.addEventListener("click", () => { draft.robot[key] = opt.id; buildControls(isHire); refreshPreview(); });
      grid.appendChild(chip);
    });
    row.appendChild(grid);
    host.appendChild(row);
  });
}

function refreshPreview() {
  const stage = $("preview-stage");
  stage.innerHTML = "";
  const sprite = buildRobot(draft.robot, "ready");
  sprite.classList.add("preview-robot");
  stage.appendChild(sprite);
}

function commit() {
  if (draft.mode === "hire") {
    // place near center-ish, offset a little so stacked hires don't overlap
    const game = document.getElementById("game").getBoundingClientRect();
    const x = game.width / 2 - 64 + (Math.random() * 80 - 40);
    const y = game.height * 0.42 + (Math.random() * 60 - 30);
    actions.addAgent({ archetypeId: draft.archetypeId, name: draft.name.trim() || suggestName(), robot: draft.robot, x, y });
    toast(`${draft.name || "A new robot"} has joined the team!`);
  } else {
    actions.updateAgent(draft.agentId, { robot: draft.robot, name: draft.name.trim() || getAgent(draft.agentId).name });
    toast("Robot updated.");
  }
  close();
}
