// Lightweight client-side unread tracking for the Messages launcher.
//
// There is no server-side "last read" concept, so we persist a per-agent
// last-read timestamp in localStorage. A message counts as unread when it was
// authored by the agent (originating_turn_id !== null) and is newer than the
// stored last-read time for that agent.

import type { Message } from "../api/client";

const EVENT = "pidgin:chat-read-changed";

function storageKey(slug: string, handle: string): string {
  return `pidgin:chatLastRead:${slug}:${handle}`;
}

export function getLastRead(slug: string, handle: string): number {
  const raw = localStorage.getItem(storageKey(slug, handle));
  return raw ? Number(raw) || 0 : 0;
}

/** Mark an agent's conversation as read up to `ts` (defaults to now). */
export function markRead(slug: string, handle: string, ts: number = Date.now()): void {
  if (!slug || !handle) return;
  if (ts <= getLastRead(slug, handle)) return;
  localStorage.setItem(storageKey(slug, handle), String(ts));
  window.dispatchEvent(new Event(EVENT));
}

/** Count agent-authored messages newer than the last-read mark. */
export function unreadCount(slug: string, handle: string, messages: Message[]): number {
  const lastRead = getLastRead(slug, handle);
  return messages.filter(
    (m) => m.originating_turn_id !== null && new Date(m.created_at).getTime() > lastRead,
  ).length;
}

/** Subscribe to read-state changes; returns an unsubscribe function. */
export function onReadChange(cb: () => void): () => void {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}
