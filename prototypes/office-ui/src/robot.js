// ─────────────────────────────────────────────────────────────────────────────
// robot.js — CUSTOMIZABLE ROBOT SPRITE
// Pure render: given a `robot` config + status, returns a DOM element.
// Used both on the office floor and (scaled up) in the customization editor.
// ─────────────────────────────────────────────────────────────────────────────

// Darken/lighten a hex color for shading (body is a touch darker than head).
export function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const clamp = v => Math.max(0, Math.min(255, v));
  const r = clamp(((n >> 16) & 255) + amt);
  const g = clamp(((n >> 8) & 255) + amt);
  const b = clamp((n & 255) + amt);
  return "#" + [r, g, b].map(v => v.toString(16).padStart(2, "0")).join("");
}

function eyesMarkup(style) {
  if (style === "visor" || style === "cyclops") return `<span class="eye ${style}"></span>`;
  return `<span class="eye ${style}"></span><span class="eye ${style}"></span>`;
}

function antennaMarkup(type, trim) {
  if (type === "none") return "";
  // Tip/dish first so it sits at the TOP of the stalk, stalk connects down to head.
  if (type === "dish") {
    return `<div class="antenna dish">
      <div class="dish-top" style="border-bottom-color:${trim}"></div>
      <div class="antenna-stalk"></div>
    </div>`;
  }
  // ball | light  (light blinks via CSS)
  return `<div class="antenna ${type}">
    <div class="antenna-tip" style="background:${trim};color:${trim}"></div>
    <div class="antenna-stalk"></div>
  </div>`;
}

// Build a robot sprite element from a robot config.
export function buildRobot(robot, status = "ready") {
  const el = document.createElement("div");
  el.className = `robot status-${status}`;
  el.dataset.antenna = robot.antenna;
  el.innerHTML = `
    ${antennaMarkup(robot.antenna, robot.trim)}
    <div class="robot-head" style="background:${robot.chassis}">
      <div class="robot-ear l" style="background:${shade(robot.chassis, -25)}"></div>
      <div class="robot-ear r" style="background:${shade(robot.chassis, -25)}"></div>
      <div class="robot-screen" style="background:${robot.screen}">
        <div class="robot-eyes eyes-${robot.eyes}">${eyesMarkup(robot.eyes)}</div>
      </div>
      <div class="status-light"></div>
    </div>
    <div class="robot-body" style="background:${shade(robot.chassis, -22)}">
      <div class="robot-arm l" style="background:${robot.chassis}"></div>
      <div class="robot-arm r" style="background:${robot.chassis}"></div>
      <div class="robot-panel" style="background:${robot.trim}"></div>
    </div>`;
  return el;
}
