import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { devsApi, type Dev } from "../api/devs";

// One live Claude Code terminal: xterm.js on a WebSocket to the dev's PTY.

type Conn = "connecting" | "live" | "offline";

export function DevTerminal({
  slug,
  dev,
  focused,
  onFocus,
  onRestart,
  onToggleMax,
  maximized,
}: {
  slug: string;
  dev: Dev;
  focused: boolean;
  onFocus: () => void;
  onRestart: () => void;
  onToggleMax: () => void;
  maximized: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const [conn, setConn] = useState<Conn>("connecting");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Mono", "Cascadia Code", Consolas, ui-monospace, monospace',
      fontSize: 13,
      lineHeight: 1.15,
      scrollback: 5000,
      allowProposedApi: true,
      theme: {
        background: "#0c0c0e",
        foreground: "#d4d4d4",
        cursor: "#d97757",
        selectionBackground: "#3a3d55",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    termRef.current = term;
    try {
      fit.fit();
    } catch {
      /* not laid out yet */
    }

    let ws: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;

    const send = (msg: object) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };
    const connect = () => {
      setConn("connecting");
      term.reset();
      ws = new WebSocket(devsApi.wsUrl(slug, dev.id, term.cols, term.rows));
      ws.onopen = () => {
        setConn("live");
        send({ t: "resize", cols: term.cols, rows: term.rows });
      };
      ws.onmessage = (e) => term.write(typeof e.data === "string" ? e.data : "");
      ws.onclose = () => {
        if (closed) return;
        setConn("offline");
        retry = window.setTimeout(connect, 2000);
      };
    };
    connect();

    const input = term.onData((d) => send({ t: "in", d }));
    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
        send({ t: "resize", cols: term.cols, rows: term.rows });
      } catch {
        /* hidden */
      }
    });
    ro.observe(host);

    return () => {
      closed = true;
      window.clearTimeout(retry);
      ro.disconnect();
      input.dispose();
      ws?.close();
      term.dispose();
      termRef.current = null;
    };
  }, [slug, dev.id, dev.cwd, dev.session_id]);

  useEffect(() => {
    if (focused) termRef.current?.focus();
  }, [focused]);

  const folder = dev.cwd.split(/[\\/]/).filter(Boolean).pop() ?? dev.cwd;
  return (
    <div className={`dt ${focused ? "focused" : ""}`} onMouseDown={onFocus}>
      <div className="dt-bar" onDoubleClick={onToggleMax}>
        <span className={`dt-light ${conn === "live" ? (dev.status === "exited" ? "exited" : "live") : conn}`} />
        <span className="dt-name">{dev.name}</span>
        <span className="dt-cwd" title={dev.cwd}>
          {folder}
        </span>
        <span className="dt-spacer" />
        {conn !== "live" ? <span className="dt-conn">{conn === "connecting" ? "connecting…" : "reconnecting…"}</span> : null}
        <button type="button" className="dt-btn" title="Restart Claude Code (keeps the conversation)" onClick={onRestart}>
          ↻
        </button>
        <button type="button" className="dt-btn" title={maximized ? "Back to four" : "Fill the screen"} onClick={onToggleMax}>
          {maximized ? "⊞" : "⛶"}
        </button>
      </div>
      <div className="dt-host" ref={hostRef} />
    </div>
  );
}
