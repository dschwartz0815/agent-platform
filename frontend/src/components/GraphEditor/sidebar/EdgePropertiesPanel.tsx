import type { Edge } from "@xyflow/react";

// Extends Record<string, unknown> to satisfy React Flow's Edge data constraint
export interface EdgeData extends Record<string, unknown> {
  /** Human-readable label displayed on the canvas edge line. */
  label: string;
  /**
   * Routing condition value — must match what the upstream router node uses
   * as its route key (e.g. "high", "low", "approved").
   * Leave blank for unconditional edges.
   */
  condition: string;
}

interface Props {
  edge: Edge | null;
  onUpdate: (id: string, data: Partial<EdgeData>) => void;
}

export function EdgePropertiesPanel({ edge, onUpdate }: Props) {
  if (!edge) {
    return (
      <div style={{ padding: 12, color: "#9ca3af", fontSize: 13 }}>
        Click an edge to edit its properties.
      </div>
    );
  }

  const data = (edge.data ?? {}) as EdgeData;
  const label = data.label ?? (edge.label as string | undefined) ?? "";
  const condition = data.condition ?? "";

  return (
    <div style={{ padding: 12 }}>
      <div
        style={{
          fontWeight: 700,
          fontSize: 12,
          color: "#6b7280",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 8,
        }}
      >
        Edge Properties
      </div>

      <Field label="Display label">
        <input
          style={inputStyle}
          value={label}
          placeholder="e.g. High risk path"
          onChange={(e) => onUpdate(edge.id, { label: e.target.value })}
        />
        <div style={hint}>Shown on the canvas. Optional — leave blank for a clean look.</div>
      </Field>

      <Field label="Condition (router routing key)">
        <input
          style={inputStyle}
          value={condition}
          placeholder='e.g. high, low, approved'
          onChange={(e) => onUpdate(edge.id, { condition: e.target.value })}
        />
        <div style={hint}>
          The value a router node must output to follow this edge. Leave blank
          for unconditional edges (non-router connections).
        </div>
      </Field>

      <div
        style={{
          marginTop: 12,
          padding: "8px 10px",
          background: condition ? "#fff7ed" : "#f9fafb",
          border: `1px solid ${condition ? "#fed7aa" : "#e5e7eb"}`,
          borderRadius: 6,
          fontSize: 12,
          color: "#6b7280",
        }}
      >
        {condition ? (
          <>
            <strong style={{ color: "#ea580c" }}>Conditional edge</strong> — this
            edge is followed when a router outputs{" "}
            <code style={{ background: "#ffedd5", padding: "1px 4px", borderRadius: 3 }}>
              {condition}
            </code>
            .
          </>
        ) : (
          <span>
            <strong>Unconditional edge</strong> — always followed (no condition set).
          </span>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "#374151",
          display: "block",
          marginBottom: 3,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  border: "1px solid #d1d5db",
  borderRadius: 5,
  padding: "5px 8px",
  fontSize: 12,
  boxSizing: "border-box",
};

const hint: React.CSSProperties = {
  fontSize: 11,
  color: "#9ca3af",
  marginTop: 3,
  lineHeight: 1.4,
};
