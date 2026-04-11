import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listGraphRuns } from "../../api/client";
import { RunDetailDrawer } from "./RunDetailDrawer";
import type { RunSummary } from "../../types";

interface Props {
  graphId: string;
}

export function RunsTab({ graphId }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const { data: runs = [], isLoading } = useQuery<RunSummary[]>({
    queryKey: ["graph-runs", graphId, statusFilter],
    queryFn: () => listGraphRuns(graphId, statusFilter ? { status: statusFilter, limit: 100 } : { limit: 100 }),
  });

  if (isLoading) return <div>Loading runs…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <section style={styles.filters}>
        <label style={styles.filterLabel}>Status</label>
        <select
          style={styles.select}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
        </select>
        <span style={styles.count}>{runs.length} run{runs.length === 1 ? "" : "s"}</span>
      </section>

      {runs.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#374151" }}>No runs yet</div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            Run the graph from the <strong>Test</strong> tab to see execution history here.
          </div>
        </div>
      ) : (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.headRow}>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Duration</th>
                <th style={styles.th}>Source</th>
                <th style={styles.th}>Input preview</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} style={styles.row} onClick={() => setSelectedRunId(r.id)}>
                  <td style={styles.td}>{new Date(r.started_at).toLocaleString()}</td>
                  <td style={styles.td}>
                    <StatusBadge status={r.status} />
                  </td>
                  <td style={styles.td}>{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</td>
                  <td style={styles.td}>
                    <code style={styles.code}>{r.trigger_source}</code>
                  </td>
                  <td style={{ ...styles.td, ...styles.preview }}>{r.input_preview}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RunDetailDrawer
        runId={selectedRunId}
        onClose={() => setSelectedRunId(null)}
      />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === "succeeded"
    ? { bg: "#f0fdf4", fg: "#16a34a", bc: "#86efac" }
    : status === "failed"
    ? { bg: "#fef2f2", fg: "#dc2626", bc: "#fca5a5" }
    : status === "running"
    ? { bg: "#eff6ff", fg: "#2563eb", bc: "#bfdbfe" }
    : { bg: "#f3f4f6", fg: "#6b7280", bc: "#d1d5db" };
  return (
    <span style={{
      background: color.bg,
      color: color.fg,
      border: `1px solid ${color.bc}`,
      borderRadius: 3,
      padding: "1px 7px",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
    }}>
      {status}
    </span>
  );
}

const styles: Record<string, React.CSSProperties> = {
  filters: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  filterLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  select: {
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 10px",
    fontSize: 12,
    background: "#fff",
  },
  count: {
    marginLeft: "auto",
    fontSize: 11,
    color: "#9ca3af",
  },
  tableCard: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    overflow: "hidden",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  headRow: { background: "#f9fafb" },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: 700,
    fontSize: 11,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  row: { cursor: "pointer" },
  td: { padding: "9px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#4b5563",
  },
  preview: {
    fontFamily: "monospace",
    fontSize: 11,
    color: "#6b7280",
    maxWidth: 300,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
  },
};
