import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";

// One SSE connection per tab, multiplexing every server-pushed notification
// (message.created, approval.created/resolved, turn.completed, …). Components
// subscribe to a topic — or a "prefix.*" wildcard — and refetch when it fires.
//
// Events are thin: the payload only scopes the refetch; the component re-reads
// via REST. That's why a dropped event (slow client, brief disconnect) is
// harmless — the next event, or the reconnect resync below, brings it current.

type Handler = (payload: unknown) => void;

type WorkspaceEventsValue = {
  /** Subscribe to a topic ("message.created") or wildcard ("message.*").
   * Returns an unsubscribe function. Pass a stable callback (useCallback). */
  subscribe: (topic: string, handler: Handler) => () => void;
};

const WorkspaceEventsContext = createContext<WorkspaceEventsValue | null>(null);

export function WorkspaceEventsProvider({
  slug,
  children,
}: {
  slug: string;
  children: ReactNode;
}) {
  const handlersRef = useRef<Map<string, Set<Handler>>>(new Map());

  // Stable across renders so subscribers don't churn.
  const subscribeRef = useRef((topic: string, handler: Handler) => {
    const map = handlersRef.current;
    let set = map.get(topic);
    if (!set) {
      set = new Set();
      map.set(topic, set);
    }
    set.add(handler);
    return () => {
      set!.delete(handler);
      if (set!.size === 0) map.delete(topic);
    };
  });

  useEffect(() => {
    if (!slug) return;
    const source = new EventSource(`/${slug}/api/stream`);

    const dispatch = (topic: string, payload: unknown) => {
      handlersRef.current.get(topic)?.forEach((cb) => cb(payload));
      const prefix = `${topic.split(".")[0]}.*`;
      if (prefix !== topic) {
        handlersRef.current.get(prefix)?.forEach((cb) => cb(payload));
      }
    };

    source.onmessage = (ev) => {
      let data: { topic?: string; payload?: unknown };
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!data.topic) return;
      // On (re)connect the server sends stream.connected; nudge every subscriber
      // to resync so anything missed while disconnected is picked up.
      if (data.topic === "stream.connected") {
        handlersRef.current.forEach((set) => set.forEach((cb) => cb(undefined)));
        return;
      }
      dispatch(data.topic, data.payload);
    };

    return () => source.close();
  }, [slug]);

  return (
    <WorkspaceEventsContext.Provider value={{ subscribe: subscribeRef.current }}>
      {children}
    </WorkspaceEventsContext.Provider>
  );
}

/** Refetch when `topic` (or its wildcard) fires. `handler` must be stable. */
export function useWorkspaceEvent(topic: string, handler: Handler): void {
  const ctx = useContext(WorkspaceEventsContext);
  useEffect(() => {
    if (!ctx) return;
    return ctx.subscribe(topic, handler);
  }, [ctx, topic, handler]);
}
