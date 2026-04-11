import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Connection, Edge, Node } from "@xyflow/react";

const SIDEBAR_WIDTH_KEY = "agent-platform:sidebar-width";
const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 560;

function useSidebarResize() {
  const [width, setWidth] = useState<number>(() => {
    const v = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    return v ? Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, parseInt(v))) : 280;
  });
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);
  const widthRef = useRef(width);
  useEffect(() => { widthRef.current = width; }, [width]);

  const onHandleMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = widthRef.current;
    e.preventDefault();
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, startW.current + (e.clientX - startX.current)));
      setWidth(next);
    };
    const onUp = () => {
      if (dragging.current) {
        localStorage.setItem(SIDEBAR_WIDTH_KEY, String(widthRef.current));
        dragging.current = false;
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  return { width, onHandleMouseDown };
}

import { cloneGraph, getGraph, updateGraph } from "../../api/client";
import type { Graph, GraphEdge, GraphNode } from "../../types";
import { NODE_TYPES } from "./nodes";
import { NodePalette } from "./sidebar/NodePalette";
import { PropertiesPanel } from "./sidebar/PropertiesPanel";
import { EdgePropertiesPanel, type EdgeData } from "./sidebar/EdgePropertiesPanel";
import { RunPanel } from "../RunPanel";
import { SchemasDrawer } from "./SchemasDrawer";

interface Props {
  graphId: string;
  onBack: () => void;
}

// ---------------------------------------------------------------------------
// Conversion helpers
// ---------------------------------------------------------------------------

/**
 * React Flow node IDs are always the node_key (stable string like "assess_risk").
 * Never use the DB UUID as the RF ID — edges reference node_keys, so they must
 * match. The UUID is stored in data for bookkeeping only.
 */
function toRFNodes(nodes: GraphNode[]): Node[] {
  return nodes.map((n) => ({
    id: n.node_key,                   // ← always node_key, not UUID
    type: n.node_type,
    position: { x: n.position_x, y: n.position_y },
    data: {
      label: n.label,
      node_type: n.node_type,
      node_key: n.node_key,
      db_id: n.id,                    // keep UUID for reference; not used by RF
      config_json: n.config_json,
    },
  }));
}

function toRFEdges(edges: GraphEdge[]): Edge[] {
  return edges.map((e) => ({
    id: e.id ?? `${e.source_node_key}__${e.target_node_key}`,
    source: e.source_node_key,        // matches RF node id (= node_key)
    target: e.target_node_key,
    type: "smoothstep",
    // condition is stored in data; label mirrors it for canvas display
    label: e.condition ?? undefined,
    data: { condition: e.condition ?? "", label: e.condition ?? "" } satisfies EdgeData,
    style: { strokeDasharray: e.condition ? "4 4" : undefined },
  }));
}

/**
 * Convert RF state back to the shape the PUT /graphs/:id endpoint expects.
 * RF node IDs are node_keys, so the source/target mapping is trivial.
 */
function fromRF(
  rfNodes: Node[],
  rfEdges: Edge[],
): { nodes: Partial<GraphNode>[]; edges: Partial<GraphEdge>[] } {
  const nodes: Partial<GraphNode>[] = rfNodes.map((n) => ({
    node_key: n.id,                                                 // id === node_key
    node_type: (n.type ?? "llm") as GraphNode["node_type"],
    label: (n.data as { label: string }).label,
    config_json: (n.data as { config_json: Record<string, unknown> }).config_json ?? {},
    position_x: n.position.x,
    position_y: n.position.y,
  }));

  const edges: Partial<GraphEdge>[] = rfEdges.map((e) => {
    const edgeData = (e.data ?? {}) as EdgeData;
    return {
      source_node_key: e.source,
      target_node_key: e.target,
      // condition wins over label if both are set; empty string → null
      condition: (edgeData.condition || (e.label as string | undefined) || null) ?? null,
    };
  });

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Selection =
  | { kind: "node"; node: Node }
  | { kind: "edge"; edge: Edge }
  | null;

export function GraphEditor({ graphId, onBack }: Props) {
  const qc = useQueryClient();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { width: sidebarWidth, onHandleMouseDown } = useSidebarResize();
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [activeTab, setActiveTab] = useState<"palette" | "properties" | "run">("palette");
  const [dirty, setDirty] = useState(false);
  const [schemasOpen, setSchemasOpen] = useState(false);

  const { data: graph, isLoading } = useQuery<Graph>({
    queryKey: ["graph", graphId],
    queryFn: () => getGraph(graphId),
  });

  useEffect(() => {
    if (!graph) return;
    setRfNodes(toRFNodes(graph.nodes));
    setRfEdges(toRFEdges(graph.edges));
    setDirty(false);
  }, [graph]);

  const saveMut = useMutation({
    mutationFn: (payload: Parameters<typeof updateGraph>[1]) =>
      updateGraph(graphId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graphId] });
      qc.invalidateQueries({ queryKey: ["graphs"] });
      setDirty(false);
    },
  });

  const cloneMut = useMutation({
    mutationFn: () => cloneGraph(graphId),
    onSuccess: (cloned) => {
      qc.invalidateQueries({ queryKey: ["graphs"] });
      alert(`Cloned as "${cloned.name}" (id: ${cloned.id}). Open it from the graph list.`);
    },
  });

  // When a new edge is drawn, add it with empty edge data and immediately open
  // the edge properties panel so the user can set a condition.
  const onConnect = useCallback(
    (params: Connection) => {
      const newId = `${params.source}__${params.target}__${Date.now()}`;
      const newEdge: Edge = {
        ...params,
        id: newId,
        type: "smoothstep",
        data: { condition: "", label: "" } satisfies EdgeData,
      };
      setRfEdges((eds) => addEdge(newEdge, eds));
      setSelection({ kind: "edge", edge: newEdge });
      setActiveTab("properties");
      setDirty(true);
    },
    [setRfEdges],
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelection({ kind: "node", node });
    setActiveTab("properties");
  }, []);

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelection({ kind: "edge", edge });
    setActiveTab("properties");
  }, []);

  const onPaneClick = useCallback(() => {
    setSelection(null);
  }, []);

  const handleNodeUpdate = useCallback(
    (id: string, changes: { label?: string; config_json?: Record<string, unknown> }) => {
      setRfNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...changes } } : n)),
      );
      // If this node is selected, keep the selection in sync
      setSelection((prev) =>
        prev?.kind === "node" && prev.node.id === id
          ? { kind: "node", node: { ...prev.node, data: { ...prev.node.data, ...changes } } }
          : prev,
      );
      setDirty(true);
    },
    [setRfNodes],
  );

  const handleEdgeUpdate = useCallback(
    (id: string, data: Partial<EdgeData>) => {
      setRfEdges((eds) =>
        eds.map((e) => {
          if (e.id !== id) return e;
          const merged: EdgeData = { ...(e.data as EdgeData), ...data };
          return {
            ...e,
            data: merged,
            // Keep the canvas label in sync — show condition if no explicit label
            label: merged.label || merged.condition || undefined,
            style: { ...e.style, strokeDasharray: merged.condition ? "4 4" : undefined },
          };
        }),
      );
      // Keep selection in sync
      setSelection((prev) => {
        if (prev?.kind !== "edge" || prev.edge.id !== id) return prev;
        const merged: EdgeData = { ...(prev.edge.data as EdgeData), ...data };
        return {
          kind: "edge",
          edge: {
            ...prev.edge,
            data: merged,
            label: merged.label || merged.condition || undefined,
          },
        };
      });
      setDirty(true);
    },
    [setRfEdges],
  );

  const handleSave = () => {
    const { nodes, edges } = fromRF(rfNodes, rfEdges);
    saveMut.mutate({
      name: graph?.name,
      // @ts-expect-error partial types are compatible with the server schema
      nodes,
      // @ts-expect-error partial types are compatible with the server schema
      edges,
    });
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData("application/agent-platform-node-type");
      if (!nodeType || !reactFlowWrapper.current) return;

      const rect = reactFlowWrapper.current.getBoundingClientRect();
      const position = { x: e.clientX - rect.left - 80, y: e.clientY - rect.top - 30 };

      const nodeKey = `${nodeType}_${Date.now()}`;
      const newNode: Node = {
        id: nodeKey,
        type: nodeType,
        position,
        data: { label: nodeKey, node_type: nodeType, node_key: nodeKey, config_json: {} },
      };
      setRfNodes((nds) => [...nds, newNode]);
      setDirty(true);
    },
    [setRfNodes],
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  if (isLoading) return <div style={{ padding: 24 }}>Loading graph…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#f9fafb" }}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <button style={styles.backBtn} onClick={onBack}>
          ← Back
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>{graph?.name}</span>
          <span style={{ color: "#9ca3af", fontSize: 13 }}>v{graph?.version}</span>
          {dirty && <span style={{ color: "#f59e0b", fontSize: 12 }}>● unsaved</span>}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={styles.toolbarBtn} onClick={() => setSchemasOpen(true)}>
            Schemas
          </button>
          <button
            style={styles.toolbarBtn}
            onClick={() => cloneMut.mutate()}
            disabled={cloneMut.isPending}
          >
            Clone
          </button>
          <button
            style={{ ...styles.toolbarBtn, background: "#2563eb", color: "#fff" }}
            onClick={handleSave}
            disabled={saveMut.isPending || !dirty}
          >
            {saveMut.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Main layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar */}
        <div style={{ ...styles.sidebar, width: sidebarWidth, minWidth: sidebarWidth, maxWidth: sidebarWidth }}>
          <div style={styles.tabBar}>
            {(["palette", "properties", "run"] as const).map((tab) => (
              <button
                key={tab}
                style={{ ...styles.tab, ...(activeTab === tab ? styles.tabActive : {}) }}
                onClick={() => setActiveTab(tab)}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {activeTab === "palette" && <NodePalette />}
            {activeTab === "properties" && (
              <>
                {selection?.kind === "node" && (
                  <PropertiesPanel
                    node={selection.node}
                    onUpdate={handleNodeUpdate}
                  />
                )}
                {selection?.kind === "edge" && (
                  <EdgePropertiesPanel
                    edge={selection.edge}
                    onUpdate={handleEdgeUpdate}
                  />
                )}
                {!selection && (
                  <div style={{ padding: 12, color: "#9ca3af", fontSize: 13 }}>
                    Click a node or edge to edit its properties.
                  </div>
                )}
              </>
            )}
            {activeTab === "run" && <RunPanel graphId={graphId} />}
          </div>
        </div>

        {/* Drag handle */}
        <div
          style={styles.dragHandle}
          onMouseDown={onHandleMouseDown}
          title="Drag to resize sidebar"
        />

        {/* Canvas */}
        <div
          ref={reactFlowWrapper}
          style={{ flex: 1, height: "100%" }}
          onDrop={onDrop}
          onDragOver={onDragOver}
        >
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={(changes) => {
              onNodesChange(changes);
              setDirty(true);
            }}
            onEdgesChange={(changes) => {
              onEdgesChange(changes);
              setDirty(true);
            }}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            nodeTypes={NODE_TYPES}
            fitView
            deleteKeyCode="Delete"
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>
      </div>

      {graph && (
        <SchemasDrawer
          open={schemasOpen}
          onClose={() => setSchemasOpen(false)}
          graph={graph}
        />
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  toolbar: {
    height: 52,
    background: "#fff",
    borderBottom: "1px solid #e5e7eb",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 16px",
    gap: 16,
  },
  backBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#2563eb",
    fontWeight: 600,
    fontSize: 14,
  },
  toolbarBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "6px 14px",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 13,
  },
  sidebar: {
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    flexShrink: 0,
  },
  dragHandle: {
    width: 5,
    cursor: "col-resize",
    background: "transparent",
    borderRight: "1px solid #e5e7eb",
    flexShrink: 0,
    transition: "background 0.1s",
  },
  tabBar: { display: "flex", borderBottom: "1px solid #e5e7eb" },
  tab: {
    flex: 1,
    padding: "8px 0",
    border: "none",
    background: "none",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 500,
    color: "#6b7280",
  },
  tabActive: {
    color: "#2563eb",
    borderBottom: "2px solid #2563eb",
    fontWeight: 700,
  },
};
