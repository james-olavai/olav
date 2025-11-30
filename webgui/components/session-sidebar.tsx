'use client';

import { useEffect, useState } from 'react';
import { useSessionStore, type SessionInfo } from '@/lib/stores/session-store';
import { useAuthStore } from '@/lib/stores/auth-store';
import { getSessions, deleteSession } from '@/lib/api/client';

interface SessionSidebarProps {
  onSelectSession: (threadId: string) => void;
  onNewSession: () => void;
}

export function SessionSidebar({ onSelectSession, onNewSession }: SessionSidebarProps) {
  const { token } = useAuthStore();
  const {
    sessions,
    currentSessionId,
    isLoading,
    error,
    setSessions,
    setCurrentSession,
    removeSession,
    setLoading,
    setError,
  } = useSessionStore();
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Fetch sessions on mount and when token changes
  useEffect(() => {
    if (!token) return;

    const fetchSessions = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getSessions(token);
        // Map API response to SessionInfo format
        const sessionList: SessionInfo[] = data.map((s) => ({
          thread_id: s.thread_id,
          created_at: s.updated_at, // Use updated_at as created_at fallback
          updated_at: s.updated_at,
          message_count: s.message_count,
          first_message: s.title,
          workflow_type: null,
        }));
        setSessions(sessionList, sessionList.length);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载会话失败');
      } finally {
        setLoading(false);
      }
    };

    fetchSessions();
  }, [token, setSessions, setLoading, setError]);

  const handleSelectSession = (threadId: string) => {
    setCurrentSession(threadId);
    onSelectSession(threadId);
  };

  const handleDeleteSession = async (threadId: string) => {
    if (!token) return;
    
    try {
      await deleteSession(threadId, token);
      removeSession(threadId);
      setDeleteConfirm(null);
    } catch (err) {
      console.error('Delete session failed:', err);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) {
      return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } else if (days === 1) {
      return '昨天';
    } else if (days < 7) {
      return `${days}天前`;
    } else {
      return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    }
  };

  const truncateText = (text: string | null, maxLength: number = 30) => {
    if (!text) return '新会话';
    return text.length > maxLength ? text.slice(0, maxLength) + '...' : text;
  };

  return (
    <div className="flex h-full w-64 flex-col border-r border-border bg-background/50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">会话历史</h2>
        <button
          onClick={onNewSession}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
          title="新建会话"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-5 w-5"
          >
            <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
          </svg>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center p-4">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : error ? (
          <div className="p-4 text-center text-sm text-red-500">{error}</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">
            暂无会话记录
            <br />
            <span className="text-xs">开始一个新的对话吧</span>
          </div>
        ) : (
          <ul className="space-y-1 p-2">
            {sessions.map((session) => (
              <li key={session.thread_id} className="relative">
                <button
                  onClick={() => handleSelectSession(session.thread_id)}
                  className={`group flex w-full items-start rounded-lg px-3 py-2 text-left transition-colors ${
                    currentSessionId === session.thread_id
                      ? 'bg-primary/10 text-primary'
                      : 'hover:bg-secondary'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {truncateText(session.first_message)}
                    </p>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{formatDate(session.updated_at)}</span>
                      <span>•</span>
                      <span>{session.message_count} 条消息</span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteConfirm(session.thread_id);
                    }}
                    className="ml-2 rounded p-1 opacity-0 hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
                    title="删除会话"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="h-4 w-4"
                    >
                      <path
                        fillRule="evenodd"
                        d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </button>
                </button>

                {/* Delete confirmation popup */}
                {deleteConfirm === session.thread_id && (
                  <div className="absolute right-0 top-full z-10 mt-1 rounded-lg border border-border bg-background p-3 shadow-lg">
                    <p className="mb-2 text-sm">确定删除此会话?</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setDeleteConfirm(null)}
                        className="rounded px-2 py-1 text-xs hover:bg-secondary"
                      >
                        取消
                      </button>
                      <button
                        onClick={() => handleDeleteSession(session.thread_id)}
                        className="rounded bg-red-500 px-2 py-1 text-xs text-white hover:bg-red-600"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Footer with session count */}
      <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
        共 {sessions.length} 个会话
      </div>
    </div>
  );
}
