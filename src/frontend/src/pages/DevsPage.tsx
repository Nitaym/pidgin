import { useCallback, useEffect, useState } from "react";
import { devsApi, type Dev } from "../api/devs";
import { DevTerminal } from "../components/DevTerminal";
import { useApp } from "../context/AppContext";
import "../styles/devs.css";

// Devs: live Claude Code terminals you type into, four on screen at once.

const SLOTS = 4;
const SLOT_KEY = "pidgin.devs.slots";

function loadSlots(): string[] {
  try {
    const raw = window.localStorage.getItem(SLOT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveSlots(slots: string[]) {
  try {
    window.localStorage.setItem(SLOT_KEY, JSON.stringify(slots));
  } catch {
    /* private window */
  }
}

export function DevsPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [devs, setDevs] = useState<Dev[] | null>(null);
  const [defaultCwd, setDefaultCwd] = useState("");
  const [slots, setSlots] = useState<string[]>(loadSlots);
  const [focus, setFocus] = useState(0);
  const [maxed, setMaxed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCwd, setNewCwd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await devsApi.list(slug);
      setDevs(data.devs);
      setDefaultCwd(data.default_cwd);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [slug]);

  useEffect(() => {
    if (!slug) return;
    void load();
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [load, slug]);

  // Keep the four slots filled with live devs, in menu order.
  useEffect(() => {
    if (!devs) return;
    const ids = new Set(devs.map((d) => d.id));
    const kept = slots.filter((id) => ids.has(id)).slice(0, SLOTS);
    for (const d of devs) {
      if (kept.length >= SLOTS) break;
      if (!kept.includes(d.id)) kept.push(d.id);
    }
    if (kept.join() !== slots.join()) {
      setSlots(kept);
      saveSlots(kept);
    }
  }, [devs, slots]);

  const show = (id: string) => {
    const at = slots.indexOf(id);
    if (at >= 0) {
      setFocus(at);
      return;
    }
    const next = [...slots];
    const slot = next.length < SLOTS ? next.length : focus;
    next[slot] = id;
    setSlots(next);
    saveSlots(next);
    setFocus(slot);
  };

  const add = async () => {
    try {
      const dev = await devsApi.add(slug, { name: newName || undefined, cwd: newCwd || undefined });
      setAdding(false);
      setNewName("");
      setNewCwd("");
      await load();
      show(dev.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (dev: Dev) => {
    if (!window.confirm(`Remove ${dev.name}? Its Claude Code process stops (the conversation stays on disk).`)) return;
    await devsApi.remove(slug, dev.id);
    await load();
  };

  const rename = async (dev: Dev, name: string) => {
    setEditing(null);
    if (name.trim() && name.trim() !== dev.name) {
      await devsApi.patch(slug, dev.id, { name: name.trim() });
      await load();
    }
  };

  if (!devs) {
    return <div className="stack">{error ? <div className="error">{error}</div> : <p className="muted">Starting devs…</p>}</div>;
  }
  const byId = new Map(devs.map((d) => [d.id, d]));
  const shown = slots.map((id) => byId.get(id)).filter((d): d is Dev => Boolean(d));
  const visible = maxed ? shown.filter((_, i) => i === focus) : shown;
  const running = devs.filter((d) => d.status === "running").length;

  return (
    <div className="devs">
      <aside className="devs-menu">
        <div className="devs-menu-head">
          <div>
            <div className="devs-title">Devs</div>
            <div className="devs-sub">
              {running} running · {devs.length} total
            </div>
          </div>
        </div>
        <ul className="devs-list">
          {devs.map((d) => {
            const slot = slots.indexOf(d.id);
            return (
              <li
                key={d.id}
                className={`${slot >= 0 ? "on" : ""} ${slot === focus && slot >= 0 ? "focus" : ""}`}
                onClick={() => show(d.id)}
              >
                <span className={`devs-dot ${d.status}`} />
                <div className="devs-item">
                  {editing === d.id ? (
                    <input
                      autoFocus
                      defaultValue={d.name}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={(e) => void rename(d, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void rename(d, (e.target as HTMLInputElement).value);
                        if (e.key === "Escape") setEditing(null);
                      }}
                    />
                  ) : (
                    <span className="devs-name" onDoubleClick={() => setEditing(d.id)}>
                      {d.name}
                    </span>
                  )}
                  <span className="devs-cwd" title={d.cwd}>
                    {d.cwd.split(/[\\/]/).filter(Boolean).pop()}
                  </span>
                </div>
                {slot >= 0 ? <span className="devs-slot">{slot + 1}</span> : null}
                <button
                  type="button"
                  className="devs-x"
                  title="Remove"
                  onClick={(e) => {
                    e.stopPropagation();
                    void remove(d);
                  }}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
        {adding ? (
          <div className="devs-add-form">
            <input placeholder="Name (optional)" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <input placeholder={defaultCwd} value={newCwd} onChange={(e) => setNewCwd(e.target.value)} title="Folder it works in" />
            <div className="row" style={{ gap: 6 }}>
              <button type="button" onClick={() => void add()}>
                Add
              </button>
              <button type="button" className="ghost" onClick={() => setAdding(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="devs-add" onClick={() => setAdding(true)}>
            + Add dev
          </button>
        )}
        {error ? <div className="devs-err">{error}</div> : null}
        <p className="devs-hint">Click a dev to put it on screen. Double-click a name to rename it, or a terminal's bar to fill the screen.</p>
      </aside>
      <section className={`devs-grid n${visible.length}`}>
        {visible.map((d) => {
          const i = shown.indexOf(d);
          return (
            <DevTerminal
              key={d.id}
              slug={slug}
              dev={d}
              focused={i === focus}
              maximized={maxed}
              onFocus={() => setFocus(i)}
              onToggleMax={() => {
                setFocus(i);
                setMaxed((m) => !m);
              }}
              onRestart={() => void devsApi.restart(slug, d.id).then(load)}
            />
          );
        })}
        {visible.length === 0 ? <div className="devs-empty">Add a dev to start.</div> : null}
      </section>
    </div>
  );
}
