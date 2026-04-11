import type { Graph } from "../../types";

interface Props {
  graph: Graph;
}

export function OverviewTab({ graph }: Props) {
  const nodeCount = graph.nodes?.length ?? 0;
  const edgeCount = graph.edges?.length ?? 0;
  const hasSchema = Boolean(graph.input_schema && graph.output_schema);

  return (
    <div style={styles.grid}>
      <section style={styles.card}>
        <div style={styles.sectionLabel}>Graph</div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Slug</span>
          <code style={styles.code}>{graph.slug ?? "—"}</code>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Nodes</span>
          <span>{nodeCount}</span>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Edges</span>
          <span>{edgeCount}</span>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Retention</span>
          <span>{graph.retention_days} days</span>
        </div>
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Publish state</div>
        {graph.latest_version_number ? (
          <>
            <div style={styles.big}>v{graph.latest_version_number}</div>
            <div style={{ color: "#6b7280", fontSize: 12 }}>
              Latest published version
            </div>
          </>
        ) : (
          <div style={styles.emptyState}>
            Draft only — not yet published. Use the <strong>Publish</strong> button above to create v1.
          </div>
        )}
        <div style={styles.row}>
          <span style={styles.rowLabel}>Schemas</span>
          <span style={{ color: hasSchema ? "#16a34a" : "#d97706" }}>
            {hasSchema ? "✓ declared" : "⚠ missing"}
          </span>
        </div>
      </section>

      <section style={{ ...styles.card, gridColumn: "1 / -1" }}>
        <div style={styles.sectionLabel}>Graph structure</div>
        {nodeCount === 0 ? (
          <div style={styles.emptyState}>This graph has no nodes. Click Edit to build it.</div>
        ) : (
          <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
            {graph.nodes.map((n) => (
              <li key={n.id} style={{ fontSize: 13, marginBottom: 3 }}>
                <code style={styles.code}>{n.node_key}</code>
                <span style={{ marginLeft: 6, color: "#6b7280" }}>
                  {n.node_type} · {n.label}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  grid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
  },
  card: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    padding: "5px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  rowLabel: { color: "#6b7280" },
  code: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
    color: "#374151",
  },
  big: { fontSize: 32, fontWeight: 800, color: "#2563eb" },
  emptyState: {
    color: "#6b7280",
    fontSize: 13,
    padding: "6px 0",
  },
};
