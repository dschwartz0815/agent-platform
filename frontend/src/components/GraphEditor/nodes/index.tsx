import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

interface NodeData {
  label: string;
  node_type: string;
  config_json: Record<string, unknown>;
  selected?: boolean;
}

const NODE_COLORS: Record<string, { bg: string; border: string; badge: string }> = {
  llm:      { bg: "#eff6ff", border: "#3b82f6", badge: "#2563eb" },
  agent:    { bg: "#f0fdf4", border: "#22c55e", badge: "#16a34a" },
  a2a:      { bg: "#ecfeff", border: "#06b6d4", badge: "#0891b2" },
  mcp_tool: { bg: "#faf5ff", border: "#a855f7", badge: "#7c3aed" },
  router:   { bg: "#fff7ed", border: "#f97316", badge: "#ea580c" },
};

const NODE_LABELS: Record<string, string> = {
  llm:      "LLM",
  agent:    "ReAct Agent",
  a2a:      "A2A Agent",
  mcp_tool: "MCP Tool",
  router:   "Router",
};

function BaseNode({
  data,
  type,
}: NodeProps & { data: NodeData; type: string }) {
  const colors = NODE_COLORS[type] ?? NODE_COLORS.llm;
  const label = NODE_LABELS[type] ?? type;

  return (
    <div
      style={{
        background: colors.bg,
        border: `2px solid ${colors.border}`,
        borderRadius: 10,
        padding: "10px 14px",
        minWidth: 160,
        boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: colors.border }} />

      <div
        style={{
          background: colors.badge,
          color: "#fff",
          fontSize: 10,
          fontWeight: 700,
          borderRadius: 4,
          padding: "1px 6px",
          display: "inline-block",
          marginBottom: 4,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
      <div style={{ fontWeight: 600, fontSize: 13, color: "#1f2937" }}>{data.label}</div>
      {data.config_json?.model != null && (
        <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
          {String(data.config_json.model as string)}
        </div>
      )}
      {data.config_json?.tool_name != null && (
        <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
          {String(data.config_json.tool_name as string)}
        </div>
      )}

      <Handle type="source" position={Position.Right} style={{ background: colors.border }} />
    </div>
  );
}

// Individual exports so React Flow's nodeTypes map works
export const LLMNode     = (props: NodeProps) => <BaseNode {...(props as NodeProps & { data: NodeData })} type="llm" />;
export const AgentNode   = (props: NodeProps) => <BaseNode {...(props as NodeProps & { data: NodeData })} type="agent" />;
export const A2ANode     = (props: NodeProps) => <BaseNode {...(props as NodeProps & { data: NodeData })} type="a2a" />;
export const MCPToolNode = (props: NodeProps) => <BaseNode {...(props as NodeProps & { data: NodeData })} type="mcp_tool" />;
export const RouterNode  = (props: NodeProps) => <BaseNode {...(props as NodeProps & { data: NodeData })} type="router" />;

export const NODE_TYPES = {
  llm:      LLMNode,
  agent:    AgentNode,
  a2a:      A2ANode,
  mcp_tool: MCPToolNode,
  router:   RouterNode,
};
