"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Brain } from "lucide-react";
import { cn } from "@/lib/utils";

interface ThinkingBoxProps {
  content: string;
  defaultOpen?: boolean;
}

// Renders <think>…</think> or reasoning_content blocks from local models.
export function ThinkingBox({ content, defaultOpen = false }: ThinkingBoxProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="my-2 rounded-md border border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-950/20 text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-violet-600 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-900/30 transition-colors rounded-t-md"
      >
        <Brain className="h-3.5 w-3.5 shrink-0" />
        <span className="font-medium">Thinking</span>
        <span className="ml-auto">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      </button>
      {open && (
        <pre
          className={cn(
            "px-3 py-2 text-violet-700 dark:text-violet-300",
            "whitespace-pre-wrap break-words font-mono leading-relaxed",
            "border-t border-violet-200 dark:border-violet-800"
          )}
        >
          {content}
        </pre>
      )}
    </div>
  );
}

// Extract <think>…</think> from model output, return { thinking, rest }.
export function extractThinking(text: string): { thinking: string | null; rest: string } {
  const match = text.match(/^<think>([\s\S]*?)<\/think>\s*/);
  if (match) {
    return { thinking: match[1].trim(), rest: text.slice(match[0].length) };
  }
  return { thinking: null, rest: text };
}
