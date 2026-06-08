// ─────────────────────────────────────────────────────────────────────────────
// main.js — BOOTSTRAP
// Wires the modules together and starts the app. Data flows one way:
//   actions → store.emit() → subscribed views re-render.
// ─────────────────────────────────────────────────────────────────────────────

import { subscribe, init } from "./store.js";
import { initOverlays } from "./overlays.js";
import { initDialogue } from "./dialogue.js";
import { initWorld, renderWorld } from "./world.js";
import { initFeatures } from "./features.js";

initOverlays();
initDialogue();
initWorld();
initFeatures();

// Re-render the floor whenever state changes.
subscribe(renderWorld);

// Load the saved office from the backend (or seed a fresh one), then paint it.
init().then(renderWorld);
