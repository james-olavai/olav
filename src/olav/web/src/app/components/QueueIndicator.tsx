"use client";

import { Loader2 } from "lucide-react";

interface QueueIndicatorProps {
  state: "queued" | "admitted" | null;
}

// Consumes queue_position / queue_admitted SSE events emitted by OLAV Layer C.
// Shown above the chat input while waiting for an LLM slot.
export function QueueIndicator({ state }: QueueIndicatorProps) {
  if (!state) return null;

  return (
    <div className="flex items-center gap-2 px-4 py-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800">
      <Loader2 className="h-3 w-3 animate-spin" />
      {state === "queued"
        ? "Request queued — waiting for LLM slot…"
        : "Slot acquired, starting inference…"}
    </div>
  );
}
