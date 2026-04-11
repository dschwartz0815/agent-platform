import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cloneGraph, createGraph, deleteGraph, listGraphs } from "../../api/client";
import type { GraphSummary } from "../../types";

interface Props {
  onOpen: (id: string) => void;
}

export function GraphList({ onOpen }: Props) {
  const qc = useQueryClient();
  const { data: graphs, isLoading } = useQuery({
    queryKey: ["graphs"],
    queryFn: listGraphs,
  });

  const cloneMut = useMutation({
    mutationFn: (id: string) => cloneGraph(id),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["graphs"] });
      onOpen(g.id);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteGraph(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["graphs"] }),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createGraph({ name: "New Graph", description: "Empty graph", nodes: [], edges: [] }),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["graphs"] });
      onOpen(g.id);
    },
  });

  if (isLoading) return <div style={styles.container}>Loading graphs…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>Graphs</h2>
        <button style={styles.newBtn} onClick={() => createMut.mutate()}>
          + New Graph
        </button>
      </div>
      {!graphs?.length && (
        <p style={{ color: "#888" }}>No graphs yet. Create one or wait for seed data.</p>
      )}
      {graphs?.map((g: GraphSummary) => (
        <div key={g.id} style={styles.card}>
          <div style={styles.cardBody}>
            <div style={styles.cardTitle}>{g.name}</div>
            {g.slug && (
              <code style={styles.slug}>acme/{g.slug}</code>
            )}
            {g.description && <div style={styles.cardDesc}>{g.description}</div>}
            <div style={styles.cardMeta}>
              {g.latest_version_number
                ? <>v{g.latest_version_number} (latest)</>
                : <>draft only</>}
              {g.parent_graph_id && " · cloned"}
              {" · "}
              {new Date(g.updated_at).toLocaleDateString()}
            </div>
          </div>
          <div style={styles.cardActions}>
            <button style={styles.btn} onClick={() => onOpen(g.id)}>
              Open
            </button>
            <button
              style={styles.btn}
              onClick={() => cloneMut.mutate(g.id)}
              disabled={cloneMut.isPending}
            >
              Clone
            </button>
            <button
              style={{ ...styles.btn, color: "#e55" }}
              onClick={() => {
                if (confirm(`Delete "${g.name}"?`)) deleteMut.mutate(g.id);
              }}
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { padding: 24, maxWidth: 800, margin: "0 auto" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  newBtn: {
    background: "#2563eb", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontWeight: 600,
  },
  card: {
    border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 12,
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "#fff",
  },
  cardBody: { flex: 1 },
  cardTitle: { fontWeight: 600, fontSize: 16 },
  cardDesc: { color: "#6b7280", fontSize: 13, marginTop: 2 },
  cardMeta: { color: "#9ca3af", fontSize: 12, marginTop: 4 },
  slug: {
    display: "inline-block",
    fontFamily: "monospace",
    fontSize: 11,
    color: "#6b7280",
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
    marginTop: 3,
    marginBottom: 3,
  },
  cardActions: { display: "flex", gap: 8 },
  btn: {
    background: "#f3f4f6", border: "1px solid #d1d5db",
    borderRadius: 5, padding: "5px 12px", cursor: "pointer", fontSize: 13,
  },
};
