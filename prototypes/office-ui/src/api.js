// ─────────────────────────────────────────────────────────────────────────────
// api.js — thin client for the Python backend.
// The backend runs on port 8000 (override by setting window.PIDGIN_API before
// the app loads). We derive the host from the current page so it works whether
// the frontend is served from localhost or a LAN IP.
// ─────────────────────────────────────────────────────────────────────────────

const API = (typeof window !== "undefined" && window.PIDGIN_API)
  || `${location.protocol}//${location.hostname}:8770`;

async function req(method, path, body) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

export const loadOffice = ()      => req("GET", "/api/office");
export const saveOffice = (data)  => req("PUT", "/api/office", data);
export const loadFeatures = async () => (await req("GET", "/api/features")).text;
export const saveFeatures = (text) => req("PUT", "/api/features", { text });
