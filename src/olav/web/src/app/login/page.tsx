"use client";

import { useState, FormEvent } from "react";
import { saveToken, saveApiUrl, getApiUrl } from "@/lib/auth";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [apiUrl, setApiUrl] = useState(getApiUrl() || "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const base = apiUrl.replace(/\/$/, "") || window.location.origin;

    try {
      const res = await fetch(`${base}/agents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        saveToken(token);
        if (apiUrl) saveApiUrl(apiUrl);
        // Use ?token= so server sets session cookie then redirects clean to /
        window.location.href = `${base}/?token=${encodeURIComponent(token)}`;
      } else if (res.status === 401) {
        setError("Invalid token. Please try again.");
      } else {
        setError(`Server returned ${res.status}. Is OLAV running at ${base}?`);
      }
    } catch {
      setError(`Cannot reach OLAV at ${base}. Check the URL.`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      fontFamily: "monospace",
      background: "#1a1a2e",
      color: "#e0e0e0",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      margin: 0,
      padding: "1rem",
    }}>
      <div style={{
        background: "#16213e",
        border: "1px solid #0f3460",
        borderRadius: "8px",
        padding: "2rem",
        width: "100%",
        maxWidth: "340px",
      }}>
        <h2 style={{
          color: "#e94560",
          marginBottom: "1.5rem",
          textAlign: "center",
          fontSize: "1.4rem",
          fontWeight: "bold",
          letterSpacing: "0.05em",
        }}>
          ⚡ OLAV
        </h2>

        <form onSubmit={handleSubmit}>
          <label style={{ display: "block", marginBottom: "0.25rem", color: "#a0a0b0", fontSize: "0.85rem" }}>
            Token
          </label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="olav_…"
            required
            autoFocus
            autoComplete="current-password"
            style={{
              width: "100%",
              boxSizing: "border-box",
              padding: "0.5rem",
              border: "1px solid #0f3460",
              background: "#0f3460",
              color: "#e0e0e0",
              borderRadius: "4px",
              marginBottom: "1rem",
              fontFamily: "monospace",
              fontSize: "0.9rem",
            }}
          />

          {error && (
            <div style={{ color: "#e94560", fontSize: "0.85rem", marginBottom: "0.75rem" }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !token}
            style={{
              width: "100%",
              padding: "0.6rem",
              background: loading || !token ? "#7a2232" : "#e94560",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: loading || !token ? "not-allowed" : "pointer",
              fontFamily: "monospace",
              fontSize: "0.95rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "0.5rem",
              opacity: loading || !token ? 0.7 : 1,
            }}
          >
            {loading && <Loader2 style={{ width: 14, height: 14, animation: "spin 1s linear infinite" }} />}
            Login
          </button>

          <div style={{ marginTop: "1rem", textAlign: "center" }}>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              style={{
                background: "none",
                border: "none",
                color: "#a0a0b0",
                fontSize: "0.75rem",
                cursor: "pointer",
                fontFamily: "monospace",
              }}
            >
              {showAdvanced ? "▲ hide advanced" : "▼ advanced"}
            </button>
          </div>

          {showAdvanced && (
            <div style={{ marginTop: "0.75rem" }}>
              <label style={{ display: "block", marginBottom: "0.25rem", color: "#a0a0b0", fontSize: "0.85rem" }}>
                Server URL
              </label>
              <input
                type="url"
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder={typeof window !== "undefined" ? window.location.origin : "http://localhost:2280"}
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  padding: "0.5rem",
                  border: "1px solid #0f3460",
                  background: "#0f3460",
                  color: "#e0e0e0",
                  borderRadius: "4px",
                  fontFamily: "monospace",
                  fontSize: "0.85rem",
                }}
              />
            </div>
          )}
        </form>

        <p style={{ marginTop: "1.5rem", color: "#555577", fontSize: "0.75rem", textAlign: "center" }}>
          OLAV Network Operations AI Platform
        </p>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
