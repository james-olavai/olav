/**
 * Zustand Store - Session History State
 */

import { create } from 'zustand';

export interface SessionInfo {
  thread_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  first_message: string | null;
  workflow_type: string | null;
}

interface SessionState {
  sessions: SessionInfo[];
  currentSessionId: string | null;
  isLoading: boolean;
  error: string | null;
  total: number;

  // Actions
  setSessions: (sessions: SessionInfo[], total: number) => void;
  setCurrentSession: (sessionId: string | null) => void;
  addSession: (session: SessionInfo) => void;
  removeSession: (sessionId: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearSessions: () => void;
}

export const useSessionStore = create<SessionState>()((set, get) => ({
  sessions: [],
  currentSessionId: null,
  isLoading: false,
  error: null,
  total: 0,

  setSessions: (sessions: SessionInfo[], total: number) => {
    set({ sessions, total, error: null });
  },

  setCurrentSession: (sessionId: string | null) => {
    set({ currentSessionId: sessionId });
  },

  addSession: (session: SessionInfo) => {
    set((state) => ({
      sessions: [session, ...state.sessions],
      total: state.total + 1,
    }));
  },

  removeSession: (sessionId: string) => {
    set((state) => ({
      sessions: state.sessions.filter((s) => s.thread_id !== sessionId),
      total: Math.max(0, state.total - 1),
      currentSessionId:
        state.currentSessionId === sessionId ? null : state.currentSessionId,
    }));
  },

  setLoading: (loading: boolean) => {
    set({ isLoading: loading });
  },

  setError: (error: string | null) => {
    set({ error });
  },

  clearSessions: () => {
    set({ sessions: [], currentSessionId: null, total: 0, error: null });
  },
}));
