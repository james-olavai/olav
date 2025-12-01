/**
 * Inspections Store - Zustand state management for inspection configurations
 */

import { create } from 'zustand';
import type { InspectionConfig, InspectionRunResponse } from '@/lib/api/types';
import { getInspections, getInspection, runInspection } from '@/lib/api/client';

interface InspectionsState {
  // Data
  inspections: InspectionConfig[];
  selectedInspection: InspectionConfig | null;
  
  // Loading states
  isLoading: boolean;
  isRunning: boolean;
  
  // Error state
  error: string | null;
  
  // Last run result
  lastRunResult: InspectionRunResponse | null;
  
  // Actions
  fetchInspections: (token: string) => Promise<void>;
  selectInspection: (id: string, token: string) => Promise<void>;
  clearSelection: () => void;
  runSelectedInspection: (token: string, devices?: string[], checks?: string[]) => Promise<InspectionRunResponse | null>;
  clearError: () => void;
}

export const useInspectionsStore = create<InspectionsState>((set, get) => ({
  // Initial state
  inspections: [],
  selectedInspection: null,
  isLoading: false,
  isRunning: false,
  error: null,
  lastRunResult: null,

  // Fetch all inspections
  fetchInspections: async (token: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await getInspections(token);
      set({ inspections: response.inspections, isLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch inspections';
      set({ error: message, isLoading: false });
    }
  },

  // Select and fetch details of a specific inspection
  selectInspection: async (id: string, token: string) => {
    set({ isLoading: true, error: null });
    try {
      const inspection = await getInspection(id, token);
      set({ selectedInspection: inspection, isLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch inspection';
      set({ error: message, isLoading: false });
    }
  },

  // Clear selection
  clearSelection: () => {
    set({ selectedInspection: null, lastRunResult: null });
  },

  // Run the selected inspection
  runSelectedInspection: async (token: string, devices?: string[], checks?: string[]) => {
    const { selectedInspection } = get();
    if (!selectedInspection) {
      set({ error: 'No inspection selected' });
      return null;
    }

    set({ isRunning: true, error: null, lastRunResult: null });
    try {
      const result = await runInspection(selectedInspection.id, token, { devices, checks });
      set({ lastRunResult: result, isRunning: false });
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to run inspection';
      set({ error: message, isRunning: false });
      return null;
    }
  },

  // Clear error
  clearError: () => {
    set({ error: null });
  },
}));
