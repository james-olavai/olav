export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status?: "pending" | "running" | "success" | "error" | "completed" | "interrupted";
}

export interface SubAgent {
  id: string;
  name: string;
  subAgentName: string;
  input?: unknown;
  output?: unknown;
  status?: "pending" | "running" | "success" | "error" | "completed" | "interrupted";
}

export interface FileItem {
  path: string;
  content: string;
}

export interface TodoItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "done" | "cancelled" | "completed";
  updatedAt?: string;
}

export interface ThreadItem {
  id: string;
  title: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  status?: "idle" | "busy" | "interrupted" | "error";
}

export interface ActionRequest {
  name: string;
  args: Record<string, unknown>;
  description?: string;
}

export interface ReviewConfig {
  actionName: string;
  allowedDecisions?: ("approve" | "reject" | "edit")[];
}

export interface ToolApprovalInterruptData {
  action_requests: ActionRequest[];
  review_configs?: ReviewConfig[];
}

// OLAV queue state from Layer C SSE events
export type QueueState = "queued" | "admitted" | null;
