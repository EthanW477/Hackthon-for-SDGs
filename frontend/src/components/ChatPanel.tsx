"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { sendChat, type ChatMessage } from "@/lib/api";

/**
 * Phase-0 chat panel: message list + input wired to the backend
 * POST /api/v1/chat stub. Phase 2 (step 2.3) adds map-linked annotations
 * (rejected route in red, suggested route in green) and citations.
 */
export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Hi, I'm UTM Copilot (低空通). Ask me about airspace, flight plan checks, or test scenarios.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  async function onSend() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    try {
      const res = await sendChat(text);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Backend unreachable — is `uvicorn app.main:app --port 43124` running?",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-4 py-3">
        <h1 className="text-sm font-semibold">UTM Copilot 低空通</h1>
        <p className="text-xs text-muted-foreground">
          Natural-language interface for Hong Kong drone traffic management
        </p>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "ml-8 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                : "mr-8 rounded-lg bg-muted px-3 py-2 text-sm"
            }
          >
            {m.content}
          </div>
        ))}
        {sending && (
          <div className="mr-8 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            Thinking…
          </div>
        )}
      </div>

      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
      >
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask in plain language…"
          disabled={sending}
        />
        <Button type="submit" disabled={sending || !draft.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}
