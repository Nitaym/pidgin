// ─────────────────────────────────────────────────────────────────────────────
// features.js — "Missing Features" editor.
// Loads MISSING_FEATURES.md as raw text from the backend, lets you edit it in a
// plain textarea, and saves it back. No markdown parsing — just text.
// ─────────────────────────────────────────────────────────────────────────────

import { loadFeatures, saveFeatures } from "./api.js";
import { toast } from "./overlays.js";

const $ = id => document.getElementById(id);

async function open() {
  $("features-overlay").classList.add("open");
  const ta = $("features-text");
  ta.value = "Loading…";
  ta.disabled = true;
  try {
    ta.value = await loadFeatures();
  } catch (err) {
    ta.value = "(Could not load features — is the backend running on :8000?)";
  }
  ta.disabled = false;
  ta.focus();
}

function close() { $("features-overlay").classList.remove("open"); }

async function save() {
  try {
    await saveFeatures($("features-text").value);
    toast("Features saved.");
    close();
  } catch (err) {
    toast("Save failed — is the backend running?");
  }
}

export function initFeatures() {
  $("features-btn").addEventListener("click", open);
  $("features-cancel").addEventListener("click", close);
  $("features-save").addEventListener("click", save);
  $("features-overlay").addEventListener("click", e => {
    if (e.target === $("features-overlay")) close();
  });
}
