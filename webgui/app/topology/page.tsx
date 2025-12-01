'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/stores/auth-store';
import { useTopologyStore } from '@/lib/stores/topology-store';
import { getTopology } from '@/lib/api/client';
import { NetworkTopology } from '@/components/network-topology';
import type { TopologyNode } from '@/lib/api/types';

// Device detail panel component
function DeviceDetailPanel({ device, onClose }: { device: TopologyNode; onClose: () => void }) {
  return (
    <div className="absolute right-4 top-20 z-10 w-80 rounded-lg border border-border bg-background p-4 shadow-xl">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{device.hostname}</h3>
        <button
          onClick={onClose}
          className="rounded p-1 hover:bg-secondary"
        >
          ✕
        </button>
      </div>
      
      <div className="mt-4 space-y-3">
        <div className="flex items-center gap-2">
          <span className={`h-3 w-3 rounded-full ${device.status === 'up' ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm">{device.status === 'up' ? '在线' : '离线'}</span>
        </div>
        
        {device.device_type && (
          <div>
            <span className="text-xs text-muted-foreground">设备类型</span>
            <p className="text-sm">{device.device_type}</p>
          </div>
        )}
        
        {device.vendor && (
          <div>
            <span className="text-xs text-muted-foreground">厂商</span>
            <p className="text-sm">{device.vendor}</p>
          </div>
        )}
        
        {device.model && (
          <div>
            <span className="text-xs text-muted-foreground">型号</span>
            <p className="text-sm">{device.model}</p>
          </div>
        )}
        
        {device.management_ip && (
          <div>
            <span className="text-xs text-muted-foreground">管理 IP</span>
            <p className="font-mono text-sm">{device.management_ip}</p>
          </div>
        )}
      </div>
      
      <div className="mt-4 flex gap-2">
        <a
          href={`/chat?query=查询 ${device.hostname} 状态`}
          className="flex-1 rounded-lg bg-primary px-3 py-2 text-center text-sm text-primary-foreground hover:bg-primary/90"
        >
          查询状态
        </a>
      </div>
    </div>
  );
}

export default function TopologyPage() {
  const router = useRouter();
  const { token, _hasHydrated } = useAuthStore();
  const {
    nodes,
    edges,
    isLoading,
    error,
    lastUpdated,
    selectedNodeId,
    setTopology,
    setLoading,
    setError,
    selectNode,
  } = useTopologyStore();
  
  const [selectedDevice, setSelectedDevice] = useState<TopologyNode | null>(null);

  // Redirect if not authenticated (wait for hydration first)
  useEffect(() => {
    if (_hasHydrated && !token) {
      router.push('/login');
    }
  }, [_hasHydrated, token, router]);

  // Fetch topology data
  useEffect(() => {
    if (!token) return;

    const fetchTopology = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getTopology(token);
        setTopology(data.nodes, data.edges, data.last_updated || undefined);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载拓扑失败');
      } finally {
        setLoading(false);
      }
    };

    fetchTopology();
  }, [token, setTopology, setLoading, setError]);

  // Handle node click
  const handleNodeClick = (node: TopologyNode) => {
    setSelectedDevice(node);
  };

  // Handle refresh
  const handleRefresh = async () => {
    if (!token) return;
    
    setLoading(true);
    setError(null);
    try {
      const data = await getTopology(token);
      setTopology(data.nodes, data.edges, data.last_updated || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新拓扑失败');
    } finally {
      setLoading(false);
    }
  };

  // Show loading while hydrating
  if (!_hasHydrated) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="relative flex h-screen flex-col bg-background">
      {/* Header */}
      <header className="border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a href="/chat" className="text-muted-foreground hover:text-foreground">
              ← 返回
            </a>
            <h1 className="text-xl font-bold">网络拓扑</h1>
          </div>
          <div className="flex items-center gap-4">
            {lastUpdated && (
              <span className="text-sm text-muted-foreground">
                更新于: {new Date(lastUpdated).toLocaleString('zh-CN')}
              </span>
            )}
            <span className="text-sm text-muted-foreground">
              {nodes.length} 设备 • {edges.length} 连接
            </span>
            <button
              onClick={handleRefresh}
              disabled={isLoading}
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-secondary disabled:opacity-50"
            >
              {isLoading ? '加载中...' : '刷新'}
            </button>
          </div>
        </div>
      </header>

      {/* Topology View */}
      <div className="relative flex-1">
        {isLoading && nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mx-auto" />
              <p className="mt-4 text-muted-foreground">加载拓扑数据...</p>
            </div>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-red-500">
              <p>❌ {error}</p>
              <button
                onClick={handleRefresh}
                className="mt-4 rounded-lg bg-primary px-4 py-2 text-primary-foreground"
              >
                重试
              </button>
            </div>
          </div>
        ) : (
          <NetworkTopology onNodeClick={handleNodeClick} />
        )}

        {/* Device Detail Panel */}
        {selectedDevice && (
          <DeviceDetailPanel
            device={selectedDevice}
            onClose={() => {
              setSelectedDevice(null);
              selectNode(null);
            }}
          />
        )}
      </div>

      {/* Legend */}
      <div className="border-t border-border px-6 py-3">
        <div className="flex items-center gap-6 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-green-500" />
            <span>在线</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-red-500" />
            <span>离线</span>
          </div>
          <div className="flex items-center gap-2">
            <span>🔀</span>
            <span>路由器</span>
          </div>
          <div className="flex items-center gap-2">
            <span>🔗</span>
            <span>交换机</span>
          </div>
          <div className="flex items-center gap-2">
            <span>📡</span>
            <span>其他设备</span>
          </div>
        </div>
      </div>
    </div>
  );
}
