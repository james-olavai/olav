'use client';

import { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useTopologyStore } from '@/lib/stores/topology-store';
import type { TopologyNode, TopologyEdge } from '@/lib/api/types';

// Custom node component for network devices
function DeviceNode({ data }: { data: { label: string; device: TopologyNode } }) {
  const { device } = data;
  
  // Device type icons
  const getDeviceIcon = (type?: string) => {
    switch (type?.toLowerCase()) {
      case 'router':
        return '🔀';
      case 'switch':
        return '🔗';
      case 'firewall':
        return '🛡️';
      case 'server':
        return '🖥️';
      default:
        return '📡';
    }
  };

  const statusColor = device.status === 'up' ? 'bg-green-500' : 'bg-red-500';

  return (
    <div className="relative rounded-lg border border-border bg-background p-3 shadow-lg min-w-[120px]">
      {/* Status indicator */}
      <div className={`absolute -right-1 -top-1 h-3 w-3 rounded-full ${statusColor}`} />
      
      {/* Device icon and name */}
      <div className="flex flex-col items-center gap-1">
        <span className="text-2xl">{getDeviceIcon(device.device_type)}</span>
        <span className="font-medium text-sm">{device.hostname}</span>
      </div>
      
      {/* Device details */}
      <div className="mt-2 text-xs text-muted-foreground text-center">
        {device.device_type && <div>{device.device_type}</div>}
        {device.vendor && <div>{device.vendor}</div>}
      </div>
    </div>
  );
}

// Node types registry
const nodeTypes = {
  device: DeviceNode,
};

interface NetworkTopologyProps {
  onNodeClick?: (node: TopologyNode) => void;
}

export function NetworkTopology({ onNodeClick }: NetworkTopologyProps) {
  const { nodes: topologyNodes, edges: topologyEdges, selectNode } = useTopologyStore();
  
  // Convert topology data to ReactFlow format
  const initialNodes: Node[] = useMemo(() => {
    // Simple grid layout
    const cols = Math.ceil(Math.sqrt(topologyNodes.length));
    
    return topologyNodes.map((node, index) => ({
      id: node.id,
      type: 'device',
      position: {
        x: (index % cols) * 200 + 50,
        y: Math.floor(index / cols) * 150 + 50,
      },
      data: { label: node.hostname, device: node },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));
  }, [topologyNodes]);

  const initialEdges: Edge[] = useMemo(() => {
    return topologyEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.source_port && edge.target_port 
        ? `${edge.source_port} ↔ ${edge.target_port}` 
        : undefined,
      labelStyle: { fontSize: 10, fill: '#666' },
      labelBgStyle: { fill: 'white', fillOpacity: 0.8 },
      style: { stroke: '#666', strokeWidth: 2 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 15,
        height: 15,
        color: '#666',
      },
      animated: false,
    }));
  }, [topologyEdges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes/edges when topology data changes
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const topologyNode = topologyNodes.find((n) => n.id === node.id);
      if (topologyNode) {
        selectNode(node.id);
        onNodeClick?.(topologyNode);
      }
    },
    [topologyNodes, selectNode, onNodeClick]
  );

  if (topologyNodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <div className="text-center">
          <span className="text-4xl">🌐</span>
          <p className="mt-2">暂无拓扑数据</p>
          <p className="text-sm">请确保 SuzieQ 已收集 LLDP 数据</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.1}
        maxZoom={2}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
      >
        <Background color="#aaa" gap={16} />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const device = (node.data as { device: TopologyNode }).device;
            return device.status === 'up' ? '#22c55e' : '#ef4444';
          }}
          maskColor="rgba(0, 0, 0, 0.1)"
        />
      </ReactFlow>
    </div>
  );
}
