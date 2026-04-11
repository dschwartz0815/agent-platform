/**
 * Drag-to-add node palette. Each item can be dragged onto the React Flow canvas.
 * The canvas's onDrop handler reads the node_type from the drag event.
 */

const PALETTE_ITEMS = [
  { type: "llm",      label: "LLM Node",     color: "#2563eb", desc: "Direct Claude call" },
  { type: "agent",    label: "ReAct Agent",  color: "#16a34a", desc: "ReAct loop with MCP tools" },
  { type: "a2a",      label: "A2A Agent",    color: "#0891b2", desc: "External A2A HTTP agent" },
  { type: "mcp_tool", label: "MCP Tool",     color: "#7c3aed", desc: "Single MCP tool call" },
  { type: "router",   label: "Router",       color: "#ea580c", desc: "Conditional branching" },
];

export function NodePalette() {
  const onDragStart = (e: React.DragEvent, nodeType: string) => {
    e.dataTransfer.setData("application/agent-platform-node-type", nodeType);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div style={{ padding: 12 }}>
      <div style={{ fontWeight: 700, fontSize: 12, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
        Node Palette
      </div>
      {PALETTE_ITEMS.map((item) => (
        <div
          key={item.type}
          draggable
          onDragStart={(e) => onDragStart(e, item.type)}
          style={{
            border: `2px solid ${item.color}`,
            borderRadius: 7,
            padding: "8px 10px",
            marginBottom: 8,
            cursor: "grab",
            background: "#fff",
          }}
        >
          <div style={{ fontWeight: 600, fontSize: 13, color: item.color }}>{item.label}</div>
          <div style={{ fontSize: 11, color: "#6b7280", marginTop: 1 }}>{item.desc}</div>
        </div>
      ))}
    </div>
  );
}
