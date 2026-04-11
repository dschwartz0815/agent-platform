import type { Usage } from "../../types";

interface Props {
  usages: Usage[];
  onOpenGraph?: (graphId: string) => void;
}

/**
 * Renders a bulleted list of graphs that reference the entity being deleted.
 * Used inside the delete-confirm modal to show what would break.
 */
export function UsageWarning({ usages, onOpenGraph }: Props) {
  if (usages.length === 0) {
    return (
      <div style={{ fontSize: 13, color: "#6b7280" }}>
        Not currently referenced by any graph.
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        ⚠ Used by {usages.length} graph{usages.length === 1 ? "" : "s"}
      </div>
      <ul style={styles.list}>
        {usages.map((u, i) => (
          <li key={`${u.graph_id}-${u.node_key}-${i}`} style={styles.item}>
            {onOpenGraph ? (
              <button
                style={styles.link}
                onClick={() => onOpenGraph(u.graph_id)}
              >
                {u.graph_name}
              </button>
            ) : (
              <strong>{u.graph_name}</strong>
            )}
            <span style={styles.nodeKey}>  ·  node <code>{u.node_key}</code></span>
          </li>
        ))}
      </ul>
      <div style={styles.explain}>
        Deleting will cause these graphs to fail at execution time with a runtime
        error until the references are removed or repointed.
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "#fffbeb",
    border: "1px solid #fcd34d",
    borderRadius: 6,
    padding: "10px 12px",
  },
  header: {
    fontWeight: 700,
    fontSize: 13,
    color: "#92400e",
    marginBottom: 6,
  },
  list: {
    margin: "4px 0 6px 18px",
    padding: 0,
    fontSize: 12,
    color: "#78350f",
  },
  item: {
    marginBottom: 3,
  },
  link: {
    background: "none",
    border: "none",
    padding: 0,
    cursor: "pointer",
    color: "#92400e",
    fontWeight: 700,
    textDecoration: "underline",
    fontSize: 12,
  },
  nodeKey: {
    color: "#a16207",
    fontSize: 11,
  },
  explain: {
    fontSize: 11,
    color: "#78350f",
    marginTop: 6,
  },
};
