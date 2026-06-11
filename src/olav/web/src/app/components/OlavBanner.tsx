"use client";

import { clearToken, getApiUrl } from "@/lib/auth";
import { LogOut, Network, Share2 } from "lucide-react";
import { useRouter } from "next/navigation";

export function OlavBanner() {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.push("/login/");
  }

  return (
    <header className="flex items-center justify-between h-10 px-3 border-b border-border bg-background shrink-0 md:h-11 md:px-4">
      <div className="flex items-center gap-2">
        <Network className="h-4 w-4 text-blue-500" />
        <span className="font-semibold text-sm tracking-tight">OLAV</span>
        <span className="hidden text-muted-foreground text-xs sm:inline">Network Operations AI</span>
      </div>
      <div className="flex items-center gap-2 md:gap-3">
        <a
          href={`${typeof window !== "undefined" ? (getApiUrl() || window.location.origin) : ""}/memory/graph`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground text-xs transition-colors"
        >
          <Share2 className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Memory Graph</span>
        </a>
        <button
          onClick={handleLogout}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-1 text-muted-foreground hover:text-foreground text-xs transition-colors sm:min-h-0 sm:min-w-0"
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      </div>
    </header>
  );
}
