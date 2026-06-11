import type { ToolCall, SubAgent } from "@/app/types/types";

export function extractStringFromMessageContent(
  content: unknown
): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (typeof c === "string") return c;
        if (c && typeof c === "object") {
          if ("text" in c && typeof c.text === "string") return c.text;
          if ("content" in c && typeof c.content === "string") return c.content;
        }
        return "";
      })
      .join("");
  }
  return String(content ?? "");
}

export function extractToolCalls(message: {
  tool_calls?: unknown[];
  additional_kwargs?: Record<string, unknown>;
}): ToolCall[] {
  const raw = message.tool_calls ?? [];
  return raw
    .filter((tc): tc is Record<string, unknown> => !!tc && typeof tc === "object")
    .map((tc) => ({
      id: String(tc.id ?? ""),
      name: String(tc.name ?? tc.function?.toString() ?? ""),
      args: (tc.args ?? tc.arguments ?? {}) as Record<string, unknown>,
      status: "pending" as const,
    }));
}

export function extractSubAgentContent(
  toolCall: ToolCall
): { subAgentName: string; input: unknown } | null {
  if (toolCall.name !== "task") return null;
  const args = toolCall.args as Record<string, unknown>;
  const subAgentName = String(args.subagent_type ?? args.agent ?? "");
  if (!subAgentName) return null;
  return { subAgentName, input: args };
}

export function isSubAgentToolCall(toolCall: ToolCall): boolean {
  return toolCall.name === "task" && !!extractSubAgentContent(toolCall);
}
