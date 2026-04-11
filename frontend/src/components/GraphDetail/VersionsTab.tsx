import { useQuery } from "@tanstack/react-query";
import { listGraphVersions } from "../../api/client";
import type { GraphVersionSummary } from "../../types";

interface Props {
  graphId: string;
}

export function VersionsTab({ graphId }: Props) {
  const { data: versions = [], isLoading } = useQuery<GraphVersionSummary[]>({
    queryKey: ["graph-versions", graphId],
    queryFn: () => listGraphVersions(graphId),
  });

  if (isLoading) return <div>Loading versions…</div>;

  if (versions.length === 0) {
    return (
      <div style={styles.empty}>
        <div style={{ fontSize: 14, color: "#374151", fontWeight: 600, marginBottom: 4 }}>
          No published versions yet
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          The current canvas state is always <code>v(latest+1)</code> draft. Edit the graph and click
          <strong> Publish v1 </strong> above to freeze the first version.
        </div>
      </div>
    );
  }

  return (
    <div style={styles.card}>
      <table style={styles.table}>
        <thead>
          <tr style={styles.headRow}>
            <th style={styles.th}>Version</th>
            <th style={styles.th}>Published</th>
            <th style={styles.th}>Notes</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td style={styles.td}>
                <code style={styles.versionCode}>v{v.version}</code>
              </td>
              <td style={styles.td}>
                {new Date(v.published_at).toLocaleString()}
              </td>
              <td style={styles.td}>{v.notes || <span style={{ color: "#9ca3af" }}>—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
  },
  card: {
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
  td: { padding: "10px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  versionCode: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#eff6ff",
    color: "#2563eb",
    padding: "2px 8px",
    borderRadius: 3,
    fontWeight: 700,
  },
};
