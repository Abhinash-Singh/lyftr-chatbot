import { useState, useRef, useEffect, useCallback } from "react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function generateSessionId() {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let id = "s-";
  for (let i = 0; i < 8; i++) {
    id += chars[Math.floor(Math.random() * chars.length)];
  }
  return id;
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [sessionId] = useState(generateSessionId);
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const body = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) {
        body.system_prompt = systemPrompt.trim();
      }

      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setMessages((prev) => [
          ...prev,
          {
            role: "error",
            content: err.detail || `Error ${res.status}`,
          },
        ]);
        return;
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply,
          metadata: data.metadata,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "error",
          content: "Network error — could not reach the server.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, sessionId, systemPrompt]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <h1>LLM Chatbot</h1>
          <span className="session-badge">Session: {sessionId}</span>
        </div>
        <div className="system-prompt-row">
          <label htmlFor="system-prompt">System Prompt</label>
          <input
            id="system-prompt"
            data-testid="system-prompt-input"
            type="text"
            placeholder="You are a helpful assistant."
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
      </header>

      <main className="chat-area">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>Send a message to start the conversation.</p>
          </div>
        )}

        {messages.map((msg, i) => {
          if (msg.role === "error") {
            return (
              <div key={i} className="message error-message">
                <div className="bubble error-bubble">{msg.content}</div>
              </div>
            );
          }

          if (msg.role === "user") {
            return (
              <div key={i} className="message user-message">
                <div className="bubble user-bubble">{msg.content}</div>
              </div>
            );
          }

          return (
            <div
              key={i}
              className="message assistant-message"
              data-testid="assistant-message"
            >
              <div className="bubble assistant-bubble">
                <p className="reply-text">{msg.content}</p>
                {msg.metadata && (
                  <div className="metadata">
                    <span
                      className={`meta-pill ${
                        msg.metadata.resolution_source === "LLM_CACHE"
                          ? "cache"
                          : "live"
                      }`}
                      data-testid="meta-source"
                    >
                      {msg.metadata.resolution_source}
                    </span>
                    <span className="meta-pill" data-testid="meta-model">
                      {msg.metadata.model}
                    </span>
                    <span className="meta-pill" data-testid="meta-latency">
                      {msg.metadata.latency_ms} ms
                    </span>
                    <span className="meta-pill" data-testid="meta-input-tokens">
                      {msg.metadata.input_tokens}
                    </span>
                    <span className="meta-pill" data-testid="meta-output-tokens">
                      {msg.metadata.output_tokens}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="message assistant-message">
            <div className="bubble assistant-bubble loading-bubble">
              <span className="dot-pulse" />
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </main>

      <footer className="input-area">
        <div className="input-row">
          <textarea
            data-testid="chat-input"
            placeholder="Type your message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading}
          />
          <button
            data-testid="send-button"
            onClick={sendMessage}
            disabled={loading || !input.trim()}
          >
            Send
          </button>
        </div>
      </footer>
    </div>
  );
}
