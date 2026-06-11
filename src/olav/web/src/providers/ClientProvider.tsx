"use client";

// OLAV fork of ClientProvider — uses Bearer token auth instead of LangSmith API key.
// Token is read from localStorage (set at /login).

import { Client } from "@langchain/langgraph-sdk";
import React, { createContext, useContext, useMemo } from "react";
import { getToken, getApiUrl } from "@/lib/auth";

interface ClientContextType {
  client: Client;
}

const ClientContext = createContext<ClientContextType | null>(null);

export function ClientProvider({
  children,
  apiUrl,
  token,
}: {
  children: React.ReactNode;
  apiUrl?: string;
  token?: string;
}) {
  const resolvedUrl = apiUrl ?? getApiUrl();
  const resolvedToken = token ?? getToken() ?? "";

  const client = useMemo(
    () =>
      new Client({
        apiUrl: resolvedUrl || window.location.origin,
        defaultHeaders: {
          Authorization: `Bearer ${resolvedToken}`,
        },
      }),
    [resolvedUrl, resolvedToken]
  );

  return (
    <ClientContext.Provider value={{ client }}>
      {children}
    </ClientContext.Provider>
  );
}

export function useClient(): Client {
  const ctx = useContext(ClientContext);
  if (!ctx) throw new Error("useClient must be inside ClientProvider");
  return ctx.client;
}
