// OLAV authentication helpers — replaces LangSmith API key flow from upstream.
// Token is stored in localStorage after successful /login POST.

const TOKEN_KEY = "olav_token";
const OLAV_API_URL_KEY = "olav_api_url";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function saveToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function getApiUrl(): string {
  if (typeof window === "undefined") return "";
  // In production (static export served by FastAPI) use same origin.
  // In dev, Next.js rewrites handle proxying to OLAV_API_URL.
  const stored = localStorage.getItem(OLAV_API_URL_KEY);
  if (stored) return stored;
  return typeof window !== "undefined" ? window.location.origin : "";
}

export function saveApiUrl(url: string): void {
  localStorage.setItem(OLAV_API_URL_KEY, url);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
