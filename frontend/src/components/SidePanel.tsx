"use client";

import { useState } from "react";
import ChatPanel from "@/components/ChatPanel";
import ScenarioPanel from "@/components/ScenarioPanel";

/** Right-hand panel: chat (Phase 2) ↔ scenario lab (Phase 3). */
export default function SidePanel() {
  const [tab, setTab] = useState<"chat" | "scenarios">("scenarios");

  return (
    <div className="flex h-full flex-col">
      <nav className="flex border-b">
        {(
          [
            { id: "scenarios", label: "Scenarios 场景" },
            { id: "chat", label: "Chat 对话" },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
              tab === t.id
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:bg-muted/50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1">{tab === "chat" ? <ChatPanel /> : <ScenarioPanel />}</div>
    </div>
  );
}
