import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listApiKeys } from "../../api/client";
import { ApiKeyFormModal } from "../ApiKeyList/ApiKeyFormModal";
import { RevealKeyModal } from "../ApiKeyList/RevealKeyModal";
import type { ApiKey, ApiKeyCreated } from "../../types";

interface Props {
  graphId: string;
}

export function KeysTab({ graphId }: Props) {
  const [formOpen, setFormOpen] = useState(false);
  const [reveal, setReveal] = useState<ApiKeyCreated | null>(null);

  const { data: allKeys = [], isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  // Filter keys that have access to this graph (wildcard OR explicitly scoped)
  const filtered = allKeys.filter(
    (k) => k.scopes.includes("*") || k.scopes.includes(graphId)
  );

  if (isLoading) return <div>Loading keys…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={styles.header}>
        <div>
          <div style={styles.title}>API keys with access to this graph</div>
          <div style={styles.subtitle}>
            Shown below are all keys whose scope includes this graph (either explicitly or via <code>*</code>).
            Manage all org-wide keys on the <strong>API Keys</strong> page.
          </div>
        </div>
        <button style={styles.newBtn} onClick={() => setFormOpen(true)}>
          + New key scoped to this graph
        </button>
      </div>

      {filtered.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
            No keys can call this graph yet
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            Create a key scoped to this graph (or a wildcard key) to enable public API access.
          </div>
        </div>
      ) : (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.headRow}>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Key</th>
                <th style={styles.th}>Scope</th>
                <th style={styles.th}>Last used</th>
                <th style={styles.th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((k) => (
                <KeyRow key={k.id} keyRow={k} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ApiKeyFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        preScopedGraphId={graphId}
        onCreated={(created) => {
          setFormOpen(false);
          setReveal(created);
        }}
      />

      <RevealKeyModal
        open={Boolean(reveal)}
        created={reveal}
        onClose={() => setReveal(null)}
      />
    </div>
  );
}

function KeyRow({ keyRow: k }: { keyRow: ApiKey }) {
  const isWild = k.scopes.includes("*");
  return (
    <tr>
      <td style={styles.td}>{k.name}</td>
      <td style={styles.td}>
        <code style={styles.prefix}>{k.key_prefix}</code>
        <span style={styles.dots}>…{k.key_last4}</span>
      </td>
      <td style={styles.td}>
        {isWild ? <span style={styles.wildBadge}>all graphs</span> : "scoped"}
      </td>
      <td style={styles.td}>
        {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : <span style={{ color: "#9ca3af" }}>never</span>}
      </td>
      <td style={styles.td}>
        {k.revoked_at ? (
          <span style={styles.revokedBadge}>REVOKED</span>
        ) : (
          <span style={styles.activeBadge}>ACTIVE</span>
        )}
      </td>
    </tr>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  title: { fontWeight: 700, fontSize: 14, color: "#111827", marginBottom: 4 },
  subtitle: {
    fontSize: 12,
    color: "#6b7280",
    maxWidth: 600,
    lineHeight: 1.5,
  },
  newBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 14px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 700,
    flexShrink: 0,
  },
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
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
  td: { padding: "9px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  prefix: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#374151",
  },
  dots: { fontFamily: "monospace", fontSize: 11, color: "#9ca3af", marginLeft: 2 },
  wildBadge: {
    background: "#fef3c7",
    color: "#92400e",
    border: "1px solid #fcd34d",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
  activeBadge: {
    background: "#f0fdf4",
    color: "#16a34a",
    border: "1px solid #86efac",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
  revokedBadge: {
    background: "#fef2f2",
    color: "#dc2626",
    border: "1px solid #fca5a5",
    borderRadius: 4,
    padding: "1px 6px",
    fontSize: 10,
    fontWeight: 700,
  },
};
