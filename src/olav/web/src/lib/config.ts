// Stub — OLAV uses auth.ts instead of the upstream LangSmith config.
// Kept for compatibility if any upstream component imports getConfig().
export interface StandaloneConfig {
  deploymentUrl: string;
  assistantId: string;
  langsmithApiKey?: string;
}

export function getConfig(): StandaloneConfig | null {
  if (typeof window === "undefined") return null;
  const { getApiUrl, getToken } = require("@/lib/auth");
  const url = getApiUrl();
  const token = getToken();
  if (!token) return null;
  return { deploymentUrl: url || window.location.origin, assistantId: "core" };
}

export function saveConfig(_config: StandaloneConfig): void {
  // no-op — OLAV config handled via auth.ts
}
