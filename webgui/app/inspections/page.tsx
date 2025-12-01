'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/stores/auth-store';
import { useInspectionsStore } from '@/lib/stores/inspections-store';
import type { InspectionConfig } from '@/lib/api/types';

export default function InspectionsPage() {
  const router = useRouter();
  const { token, isAuthenticated, _hasHydrated } = useAuthStore();
  const { 
    inspections, 
    selectedInspection, 
    isLoading, 
    isRunning,
    error, 
    lastRunResult,
    fetchInspections, 
    selectInspection,
    clearSelection,
    runSelectedInspection,
    clearError,
  } = useInspectionsStore();

  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);

  // Redirect if not authenticated (wait for hydration first)
  useEffect(() => {
    if (_hasHydrated && !isAuthenticated) {
      router.push('/login');
    }
  }, [_hasHydrated, isAuthenticated, router]);

  // Fetch inspections on mount
  useEffect(() => {
    if (token) {
      fetchInspections(token);
    }
  }, [token, fetchInspections]);

  // Update selected devices when inspection changes
  useEffect(() => {
    if (selectedInspection) {
      const devices = Array.isArray(selectedInspection.devices) 
        ? selectedInspection.devices 
        : [];
      setSelectedDevices(devices);
    }
  }, [selectedInspection]);

  const handleSelectInspection = (config: InspectionConfig) => {
    if (token) {
      selectInspection(config.id, token);
    }
  };

  const handleRunInspection = async () => {
    if (token && selectedInspection) {
      await runSelectedInspection(token, selectedDevices.length > 0 ? selectedDevices : undefined);
    }
  };

  const handleDeviceToggle = (device: string) => {
    setSelectedDevices(prev => 
      prev.includes(device) 
        ? prev.filter(d => d !== device)
        : [...prev, device]
    );
  };

  // Show loading while hydrating or not authenticated
  if (!_hasHydrated || !isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  // Get status badge color
  const getStatusBadge = (enabled: boolean) => {
    return enabled
      ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
      : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
  };

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
              🔍 巡检配置
            </h1>
          </div>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            共 {inspections.length} 个配置
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
      <div className="flex h-[calc(100vh-65px)]">
        {/* Inspection List */}
        <div className="w-1/3 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
          {isLoading && inspections.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : inspections.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-gray-400">
              <span className="text-4xl mb-4">📋</span>
              <p>暂无巡检配置</p>
              <p className="text-sm mt-2">在 config/inspections/ 目录添加 YAML 配置</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
              {inspections.map((config) => (
                <div
                  key={config.id}
                  onClick={() => handleSelectInspection(config)}
                  className={`p-4 cursor-pointer transition-colors ${
                    selectedInspection?.id === config.id
                      ? 'bg-blue-50 dark:bg-blue-900/20 border-l-4 border-blue-500'
                      : 'hover:bg-gray-50 dark:hover:bg-gray-800'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-white truncate">
                        {config.name}
                      </h3>
                      {config.description && (
                        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                          {config.description}
                        </p>
                      )}
                      <div className="flex items-center gap-2 mt-2">
                        <span className="text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-2 py-0.5 rounded">
                          {Array.isArray(config.devices) ? config.devices.length : '动态'} 设备
                        </span>
                        <span className="text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-2 py-0.5 rounded">
                          {config.checks.filter(c => c.enabled).length} 检查项
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Inspection Detail */}
        <div className="flex-1 overflow-y-auto">
          {selectedInspection ? (
            <div className="p-6">
              {/* Title & Run Button */}
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                    {selectedInspection.name}
                  </h2>
                  {selectedInspection.description && (
                    <p className="text-gray-600 dark:text-gray-400 mt-1">
                      {selectedInspection.description}
                    </p>
                  )}
                  <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
                    📁 {selectedInspection.filename}
                  </p>
                </div>
                <button
                  onClick={handleRunInspection}
                  disabled={isRunning}
                  className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                    isRunning
                      ? 'bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed'
                      : 'bg-blue-600 hover:bg-blue-700 text-white'
                  }`}
                >
                  {isRunning ? (
                    <span className="flex items-center gap-2">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                      执行中...
                    </span>
                  ) : (
                    '▶️ 执行巡检'
                  )}
                </button>
              </div>

              {/* Last Run Result */}
              {lastRunResult && (
                <div className={`mb-6 p-4 rounded-lg border ${
                  lastRunResult.status === 'started' 
                    ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
                    : lastRunResult.status === 'completed'
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                    : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                }`}>
                  <div className="flex items-center gap-2">
                    <span>{lastRunResult.status === 'started' ? '🚀' : lastRunResult.status === 'completed' ? '✅' : '❌'}</span>
                    <span className="font-medium">{lastRunResult.message}</span>
                  </div>
                  {lastRunResult.report_id && (
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                      报告 ID: {lastRunResult.report_id}
                    </p>
                  )}
                </div>
              )}

              {/* Configuration Cards */}
              <div className="grid grid-cols-2 gap-4 mb-6">
                <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                  <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">执行模式</h4>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-1 text-xs rounded ${
                      selectedInspection.parallel
                        ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                        : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
                    }`}>
                      {selectedInspection.parallel ? '并行' : '串行'}
                    </span>
                    <span className="text-gray-600 dark:text-gray-300">
                      最大 {selectedInspection.max_workers} 并发
                    </span>
                  </div>
                </div>
                <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                  <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">失败处理</h4>
                  <span className={`px-2 py-1 text-xs rounded ${
                    selectedInspection.stop_on_failure
                      ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                      : 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                  }`}>
                    {selectedInspection.stop_on_failure ? '失败时停止' : '继续执行'}
                  </span>
                </div>
              </div>

              {/* Target Devices */}
              <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 mb-6">
                <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">目标设备</h4>
                {Array.isArray(selectedInspection.devices) ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedInspection.devices.map((device) => (
                      <label
                        key={device}
                        className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                          selectedDevices.includes(device)
                            ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700'
                            : 'bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-600'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedDevices.includes(device)}
                          onChange={() => handleDeviceToggle(device)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span className="text-gray-700 dark:text-gray-200">{device}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="text-gray-600 dark:text-gray-400">
                    <p className="mb-2">动态设备选择 (NetBox Filter):</p>
                    <pre className="bg-gray-100 dark:bg-gray-900 p-3 rounded text-sm overflow-x-auto">
                      {JSON.stringify(selectedInspection.devices, null, 2)}
                    </pre>
                  </div>
                )}
              </div>

              {/* Checks */}
              <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">
                  检查项 ({selectedInspection.checks.length})
                </h4>
                <div className="space-y-3">
                  {selectedInspection.checks.map((check, index) => (
                    <div
                      key={index}
                      className={`p-3 rounded-lg border ${
                        check.enabled
                          ? 'bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600'
                          : 'bg-gray-50 dark:bg-gray-800 border-gray-100 dark:border-gray-700 opacity-60'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className={`px-2 py-0.5 text-xs rounded ${getStatusBadge(check.enabled)}`}>
                              {check.enabled ? '启用' : '禁用'}
                            </span>
                            <h5 className="font-medium text-gray-900 dark:text-white">
                              {check.name}
                            </h5>
                          </div>
                          {check.description && (
                            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                              {check.description}
                            </p>
                          )}
                          <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 dark:text-gray-400">
                            <span>🔧 {check.tool}</span>
                            {Object.keys(check.parameters).length > 0 && (
                              <span>📝 {Object.keys(check.parameters).length} 参数</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-gray-400">
              <span className="text-6xl mb-4">🔍</span>
              <p className="text-lg">选择一个巡检配置查看详情</p>
              <p className="text-sm mt-2">点击左侧列表中的配置</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
