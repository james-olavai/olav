'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/stores/auth-store';
import { useDocumentsStore } from '@/lib/stores/documents-store';

export default function DocumentsPage() {
  const router = useRouter();
  const { token, isAuthenticated } = useAuthStore();
  const { 
    documents, 
    isLoading, 
    isUploading,
    isDeleting,
    error, 
    fetchDocuments, 
    uploadFile,
    deleteDoc,
    clearError,
  } = useDocumentsStore();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, router]);

  // Fetch documents on mount
  useEffect(() => {
    if (token) {
      fetchDocuments(token);
    }
  }, [token, fetchDocuments]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0] && token) {
      await uploadFile(e.dataTransfer.files[0], token);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0] && token) {
      await uploadFile(e.target.files[0], token);
      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDelete = async (documentId: string) => {
    if (token) {
      await deleteDoc(documentId, token);
      setDeleteConfirm(null);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getFileIcon = (fileType: string): string => {
    switch (fileType.toLowerCase()) {
      case 'pdf': return '📕';
      case 'docx':
      case 'doc': return '📘';
      case 'txt': return '📄';
      case 'md': return '📝';
      case 'html': return '🌐';
      default: return '📁';
    }
  };

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/chat')}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              ← 返回聊天
            </button>
            <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
              📚 知识库文档
            </h1>
          </div>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            共 {documents.length} 个文档
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800 px-6 py-3">
          <div className="flex items-center justify-between">
            <span className="text-red-700 dark:text-red-400">{error}</span>
            <button 
              onClick={clearError}
              className="text-red-500 hover:text-red-700"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="max-w-4xl mx-auto p-6">
        {/* Upload Area */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`mb-8 border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
            dragActive
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
              : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.html"
            onChange={handleFileSelect}
            className="hidden"
          />
          
          {isUploading ? (
            <div className="flex flex-col items-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mb-4"></div>
              <p className="text-gray-600 dark:text-gray-400">正在上传...</p>
            </div>
          ) : (
            <>
              <div className="text-5xl mb-4">📤</div>
              <p className="text-lg text-gray-700 dark:text-gray-300 mb-2">
                拖拽文件到此处上传
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                或点击下方按钮选择文件
              </p>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                选择文件
              </button>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-4">
                支持格式: PDF, DOCX, TXT, MD, HTML
              </p>
            </>
          )}
        </div>

        {/* Documents List */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-750">
            <h2 className="font-medium text-gray-900 dark:text-white">已上传文档</h2>
          </div>
          
          {isLoading && documents.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500 dark:text-gray-400">
              <span className="text-4xl mb-4">📂</span>
              <p>暂无文档</p>
              <p className="text-sm mt-2">上传文档以扩展 AI 知识库</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="px-4 py-4 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors"
                >
                  <div className="flex items-center gap-4 flex-1 min-w-0">
                    <span className="text-2xl">{getFileIcon(doc.file_type)}</span>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-white truncate">
                        {doc.filename}
                      </h3>
                      <div className="flex items-center gap-3 text-sm text-gray-500 dark:text-gray-400 mt-1">
                        <span>{formatFileSize(doc.size_bytes)}</span>
                        <span>•</span>
                        <span>{doc.file_type.toUpperCase()}</span>
                        <span>•</span>
                        <span>{new Date(doc.uploaded_at).toLocaleDateString('zh-CN')}</span>
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3 ml-4">
                    {/* Index Status */}
                    <span className={`px-2 py-1 text-xs rounded ${
                      doc.indexed
                        ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                        : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
                    }`}>
                      {doc.indexed ? '已索引' : '待索引'}
                    </span>
                    
                    {doc.chunk_count > 0 && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {doc.chunk_count} chunks
                      </span>
                    )}
                    
                    {/* Delete Button */}
                    {deleteConfirm === doc.id ? (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleDelete(doc.id)}
                          disabled={isDeleting === doc.id}
                          className="px-3 py-1 text-sm bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
                        >
                          {isDeleting === doc.id ? '删除中...' : '确认'}
                        </button>
                        <button
                          onClick={() => setDeleteConfirm(null)}
                          className="px-3 py-1 text-sm bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-500 text-gray-700 dark:text-gray-200 rounded transition-colors"
                        >
                          取消
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirm(doc.id)}
                        className="p-2 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                        title="删除文档"
                      >
                        🗑️
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Info Box */}
        <div className="mt-6 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <h3 className="font-medium text-blue-800 dark:text-blue-200 mb-2">💡 提示</h3>
          <ul className="text-sm text-blue-700 dark:text-blue-300 space-y-1">
            <li>• 上传的文档会被自动分块并索引到知识库</li>
            <li>• AI 在回答问题时会参考这些文档内容</li>
            <li>• 支持网络设备手册、配置指南、最佳实践等文档</li>
            <li>• 建议上传 PDF 或 Markdown 格式以获得最佳效果</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
