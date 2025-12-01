/**
 * Documents Store - Zustand state management for RAG documents
 */

import { create } from 'zustand';
import type { DocumentSummary } from '@/lib/api/types';
import { getDocuments, deleteDocument, uploadDocument } from '@/lib/api/client';

interface DocumentsState {
  // Data
  documents: DocumentSummary[];
  
  // Loading states
  isLoading: boolean;
  isUploading: boolean;
  isDeleting: string | null;  // ID of document being deleted
  
  // Error state
  error: string | null;
  
  // Upload progress
  uploadProgress: number;
  
  // Actions
  fetchDocuments: (token: string) => Promise<void>;
  uploadFile: (file: File, token: string) => Promise<boolean>;
  deleteDoc: (documentId: string, token: string) => Promise<boolean>;
  clearError: () => void;
}

export const useDocumentsStore = create<DocumentsState>((set, get) => ({
  // Initial state
  documents: [],
  isLoading: false,
  isUploading: false,
  isDeleting: null,
  error: null,
  uploadProgress: 0,

  // Fetch all documents
  fetchDocuments: async (token: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await getDocuments(token);
      set({ documents: response.documents, isLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch documents';
      set({ error: message, isLoading: false });
    }
  },

  // Upload a file
  uploadFile: async (file: File, token: string) => {
    set({ isUploading: true, error: null, uploadProgress: 0 });
    try {
      const result = await uploadDocument(file, token);
      
      if (result.status === 'not_implemented') {
        set({ 
          error: '文件上传功能尚未完全实现', 
          isUploading: false,
          uploadProgress: 0,
        });
        return false;
      }
      
      // Refresh document list
      const { fetchDocuments } = get();
      await fetchDocuments(token);
      
      set({ isUploading: false, uploadProgress: 100 });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to upload document';
      set({ error: message, isUploading: false, uploadProgress: 0 });
      return false;
    }
  },

  // Delete a document
  deleteDoc: async (documentId: string, token: string) => {
    set({ isDeleting: documentId, error: null });
    try {
      await deleteDocument(documentId, token);
      
      // Remove from local state
      const { documents } = get();
      set({ 
        documents: documents.filter(d => d.id !== documentId),
        isDeleting: null,
      });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete document';
      set({ error: message, isDeleting: null });
      return false;
    }
  },

  // Clear error
  clearError: () => {
    set({ error: null });
  },
}));
