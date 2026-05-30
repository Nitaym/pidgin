import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Message, type Room } from "../api/client";
import { useApp } from "../context/AppContext";

export function ChatPage() {
  const { roomId = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [room, setRoom] = useState<Room | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      if (!slug) return;
      setError(null);
      try {
        const rooms = await api.listRooms(slug);
        const current = rooms.find((row) => row.id === roomId) ?? null;
        setRoom(current);
        const data = await api.getRoomMessages(slug, roomId);
        setMessages(data.messages);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load chat");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [slug, roomId]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!body.trim() || !slug) return;
    setError(null);
    try {
      const data = await api.sendRoomMessage(slug, roomId, body.trim());
      setMessages(data.messages);
      setBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    }
  }

  if (loading) {
    return <p className="muted">Loading chat…</p>;
  }

  if (!room) {
    return <div className="error">Room not found</div>;
  }

  return (
    <div className="stack">
      <p className="muted">
        <Link to="..">← Back to team</Link>
      </p>
      {error ? <div className="error">{error}</div> : null}

      <section className="panel stack">
        <h3 style={{ margin: 0 }}>{room.name}</h3>
        <div className="message-list">
          {messages.length === 0 ? (
            <p className="muted">No messages yet. Say hello.</p>
          ) : (
            messages.map((message) => {
              const isHuman = message.sender_display_name === "You";
              return (
                <div
                  key={message.id}
                  className={`message ${isHuman ? "human" : "agent"}`}
                >
                  <div className="meta">{message.sender_display_name}</div>
                  <div>{message.body_text}</div>
                </div>
              );
            })
          )}
        </div>
        <form className="row" onSubmit={handleSend}>
          <input
            style={{ flex: 1, minWidth: "12rem" }}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Type a message…"
          />
          <button type="submit">Send</button>
        </form>
      </section>
    </div>
  );
}
