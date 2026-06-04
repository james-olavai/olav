"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import { useQueryState } from "nuqs";
import { getToken, getApiUrl } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Assistant } from "@langchain/langgraph-sdk";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import { MessagesSquare, SquarePen, RefreshCw } from "lucide-react";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ThreadList } from "@/app/components/ThreadList";
import { ChatProvider } from "@/providers/ChatProvider";
import { ChatInterface } from "@/app/components/ChatInterface";
import { OlavBanner } from "@/app/components/OlavBanner";
import { useThreads } from "@/app/hooks/useThreads";
import { useMobile } from "@/app/hooks/useMobile";
import { useRouter } from "next/navigation";

function HomePageInner() {
  const client = useClient();
  const router = useRouter();
  const [threadId, setThreadId] = useQueryState("threadId");
  const [sidebar, setSidebar] = useQueryState("sidebar");

  const [mutateThreads, setMutateThreads] = useState<(() => void) | null>(null);
  const [interruptCount, setInterruptCount] = useState(0);
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [agentsRefreshing, setAgentsRefreshing] = useState(false);

  const { deleteThread } = useThreads({});
  const isMobile = useMobile();

  const fetchAssistants = useCallback(async () => {
    setAgentsRefreshing(true);
    try {
      const list = await client.assistants.search({ limit: 50 });
      if (list.length > 0) {
        setAssistants(list);
        // Preserve current selection if it still exists, else pick first
        setAssistant((prev) => {
          const still = prev ? list.find((a) => a.assistant_id === prev.assistant_id) : null;
          return still ?? list[0];
        });
      }
    } catch {
      const fallback: Assistant = {
        assistant_id: "core",
        graph_id: "core",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        config: {},
        metadata: {},
        version: 1,
        name: "core",
        context: {},
      };
      setAssistants([fallback]);
      setAssistant((prev) => prev ?? fallback);
    } finally {
      setAgentsRefreshing(false);
    }
  }, [client]);

  useEffect(() => {
    fetchAssistants();
  }, [fetchAssistants]);

  const handleAgentChange = useCallback(async (assistantId: string) => {
    const found = assistants.find((a) => a.assistant_id === assistantId);
    if (found) {
      setAssistant(found);
      await setThreadId(null); // start fresh conversation on agent switch
    }
  }, [assistants, setThreadId]);

  const threadListProps = {
    onThreadSelect: async (id: string) => { await setThreadId(id); if (isMobile) setSidebar(null); },
    onMutateReady: (fn: () => void) => setMutateThreads(() => fn),
    onClose: () => setSidebar(null),
    onInterruptCountChange: setInterruptCount,
    onDeleteThread: deleteThread,
  };

  return (
    <div className="flex h-screen flex-col">
      {/* OLAV top banner */}
      <OlavBanner />

      <div className="flex h-12 flex-shrink-0 items-center justify-between border-b border-border px-3 md:h-16 md:px-6">
        <div className="flex items-center gap-2">
          {!sidebar && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSidebar("1")}
              className="rounded-md border border-border bg-card px-2 py-2 text-foreground hover:bg-accent md:px-3"
            >
              <MessagesSquare className="h-4 w-4" />
              <span className="ml-2 hidden sm:inline">Threads</span>
              {interruptCount > 0 && (
                <span className="ml-1 inline-flex min-h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] text-destructive-foreground">
                  {interruptCount}
                </span>
              )}
            </Button>
          )}
        </div>
        <div className="flex items-center gap-1 md:gap-2">
          {/* Agent selector */}
          <div className="flex items-center gap-1">
            <select
              value={assistant?.assistant_id ?? ""}
              onChange={(e) => handleAgentChange(e.target.value)}
              className="h-8 max-w-[120px] rounded-md border border-border bg-card px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring md:h-9 md:max-w-none"
            >
              {assistants.map((a) => (
                <option key={a.assistant_id} value={a.assistant_id}>
                  {a.name || a.assistant_id}
                </option>
              ))}
            </select>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchAssistants}
              disabled={agentsRefreshing}
              title="Refresh agent list"
              className="h-8 w-8 p-0 md:h-9 md:w-9"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${agentsRefreshing ? "animate-spin" : ""}`} />
            </Button>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => { await setThreadId(null); }}
            disabled={!threadId}
            className="h-8 border-[#2F6868] bg-[#2F6868] px-2 text-white hover:bg-[#2F6868]/80 md:h-9 md:px-3"
          >
            <SquarePen className="h-4 w-4" />
            <span className="ml-2 hidden sm:inline">New Thread</span>
          </Button>
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden">
        {/* Mobile: full-screen overlay sidebar */}
        {isMobile && sidebar && (
          <>
            {/* backdrop */}
            <div
              className="absolute inset-0 z-30 bg-black/40"
              onClick={() => setSidebar(null)}
            />
            <div className="absolute inset-y-0 left-0 z-40 w-full max-w-sm bg-background shadow-xl">
              <ThreadList {...threadListProps} />
            </div>
          </>
        )}

        {/* Desktop: resizable panels.
            `key` changes when sidebar opens/closes so the group fully remounts
            and honours defaultSize on each panel from scratch. Without this,
            react-resizable-panels ignores defaultSize on a conditionally-added
            panel and assigns only the leftover ~2% instead of 28%. */}
        <ResizablePanelGroup
          orientation="horizontal"
          className="h-full"
          defaultLayout={
            !isMobile && sidebar
              ? { "thread-history": 28, "chat": 72 }
              : { "chat": 100 }
          }
        >
          {!isMobile && sidebar && (
            <>
              <ResizablePanel
                id="thread-history"
                defaultSize={28}
                minSize={22}
                className="relative z-10"
              >
                <ThreadList {...threadListProps} />
              </ResizablePanel>
              <ResizableHandle />
            </>
          )}

          <ResizablePanel
            id="chat"
            className="relative flex flex-col"
          >
            <ChatProvider
              activeAssistant={assistant}
              onHistoryRevalidate={() => mutateThreads?.()}
            >
              <ChatInterface assistant={assistant} />
            </ChatProvider>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}

function HomePageContent() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login/");
    } else {
      setReady(true);
    }
  }, [router]);

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">Checking authentication…</p>
      </div>
    );
  }

  const apiUrl = getApiUrl();

  return (
    <ClientProvider apiUrl={apiUrl}>
      <HomePageInner />
    </ClientProvider>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center">
          <p className="text-muted-foreground">Loading...</p>
        </div>
      }
    >
      <HomePageContent />
    </Suspense>
  );
}
