/**
 * Zustand Store - Network Topology State
 */

import { create } from 'zustand';
import type { TopologyNode, TopologyEdge } from '@/lib/api/types';

interface TopologyState {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  selectedNodeId: string | null;
  isLoading: boolean;
  error: string | null;
  lastUpdated: string | null;

  // Actions
  setTopology: (nodes: TopologyNode[], edges: TopologyEdge[], lastUpdated?: string) => void;
  selectNode: (nodeId: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearTopology: () => void;
}

export const useTopologyStore = create<TopologyState>()((set) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  isLoading: false,
  error: null,
  lastUpdated: null,

  setTopology: (nodes: TopologyNode[], edges: TopologyEdge[], lastUpdated?: string) => {
    set({ nodes, edges, lastUpdated: lastUpdated || null, error: null });
  },

  selectNode: (nodeId: string | null) => {
    set({ selectedNodeId: nodeId });
  },

  setLoading: (loading: boolean) => {
    set({ isLoading: loading });
  },

  setError: (error: string | null) => {
    set({ error });
  },

  clearTopology: () => {
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      error: null,
      lastUpdated: null,
    });
  },
}));
