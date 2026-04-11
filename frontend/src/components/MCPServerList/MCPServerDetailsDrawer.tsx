import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMCPServerUsages, refreshMCPServerTools } from "../../api/client";
import { Drawer } from "../shared/Drawer";
import type { MCPServer, MCPTool } from "../../types";

interface Props {
  open: boolean;
  server: MCPServer | null;
  onClose: () => void;
  onOpenGraph: (graphId: string) => void;
}

export function MCPServerDetailsDrawer({ open, server, onClose, onOpenGraph }: Props) {
  const qc = useQueryClient();
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [showEnv, setShowEnv] = useState(false);

  const { data: usages = [], isLoading: usagesLoading } = useQuery({
    queryKey: ["mcp-server-usages", server?.id],
    queryFn: () => getMCPServerUsages(server!.id),
    enabled: open && Boolean(server?.id),
    staleTime: 5_000,
  });

  const refreshMut = useMutation({
    mutationFn: () => refreshMCPServerTools(server!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
    },
  });

  if (!server) return null;

  const tools: MCPTool[] = server.tools_json ?? [];

  return (
    <Drawer open={open} title={server.name} onClose={onClose}>
      <section style={styles.section}>
        <div style={styles.sectionLabel}>Summary</div>
        <Row label="ID" value={<code style={styles.code}>{server.id}</code>} />
        <Row label="Transport" value={server.transport === "http" ? "HTTP (SSE)" : "stdio"} />
        {server.transport === "http" && (
          <Row label="URL" value={<code style={styles.code}>{server.url ?? "—"}</code>} />
        )}
        {server.transport === "stdio" && (
          <>
            <Row label="Command" value={<code style={styles.code}>{server.command ?? "—"}</code>} />
            {server.args && server.args.length > 0 && (
              <Row
                label="Args"
                value={<code style={styles.code}>{server.args.join(" ")}</code>}
              />
            )}
            {server.env_vars && Object.keys(server.env_vars).length > 0 && (
              <Row
                label="Env Vars"
                value={
                  <div>
                    <button style={styles.toggleBtn} onClick={() => setShowEnv((v) => !v)}>
                      {showEnv ? "Hide values" : `Show (${Object.keys(server.env_vars).length})`}
                    </button>
                    {showEnv && (
                      <pre style={styles.miniJson}>
                        {Object.entries(server.env_vars)
                          .map(([k, v]) => `${k}=${v}`)
                          .join("\n")}
                      </pre>
                    )}
                  </div>
                }
              />
            )}
          </>
        )}
        <Row label="Created" value={new Date(server.created_at).toLocaleString()} />
        {server.description && <Row label="Description" value={server.description} />}
      </section>

      <section style={styles.section}>
        <div style={styles.sectionHeaderRow}>
          <div style={styles.sectionLabel}>
            Tools {tools.length > 0 && <span style={{ color: "#9ca3af" }}>· {tools.length}</span>}
          </div>
          <button
            style={styles.refreshBtn}
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending}
          >
            {refreshMut.isPending ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
        {refreshMut.isError && (
          <div style={styles.errorBox}>
            Refresh failed. The server may be unreachable, or (for stdio) the command is missing on the backend filesystem.
          </div>
        )}
        {tools.length === 0 ? (
          <div style={styles.emptyBox}>
            No tools discovered yet. Click Refresh to retry.
          </div>
        ) : (
          <div>
            {tools.map((t) => {
              const isOpen = expandedTool === t.name;
              return (
                <div key={t.name} style={styles.toolCard}>
                  <div
                    style={styles.toolHeader}
                    onClick={() => setExpandedTool(isOpen ? null : t.name)}
                  >
                    <div>
                      <div style={styles.toolName}>{t.name}</div>
                      {t.description && <div style={styles.toolDesc}>{t.description}</div>}
                    </div>
                    <span style={styles.toolChevron}>{isOpen ? "−" : "+"}</span>
                  </div>
                  {isOpen && t.input_schema && (
                    <pre style={styles.schemaBox}>
                      {JSON.stringify(t.input_schema, null, 2)}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section style={styles.section}>
        <div style={styles.sectionLabel}>Used by</div>
        {usagesLoading ? (
          <div style={styles.helpText}>Checking…</div>
        ) : usages.length === 0 ? (
          <div style={styles.helpText}>Not referenced by any graph.</div>
        ) : (
          <ul style={styles.usagesList}>
            {usages.map((u, i) => (
              <li key={`${u.graph_id}-${u.node_key}-${i}`} style={styles.usageItem}>
                <button
                  style={styles.usageLink}
                  onClick={() => { onOpenGraph(u.graph_id); onClose(); }}
                >
                  {u.graph_name}
                </button>
                <span style={styles.usageNode}>  ·  node <code>{u.node_key}</code></span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Drawer>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={styles.row}>
      <div style={styles.rowLabel}>{label}</div>
      <div style={styles.rowValue}>{value}</div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  section: { marginBottom: 22 },
  sectionLabel: {
    fontSize: 11, fontWeight: 700, color: "#6b7280",
    textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8,
  },
  sectionHeaderRow: {
    display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8,
  },
  row: { display: "flex", gap: 12, marginBottom: 6, fontSize: 13 },
  rowLabel: { flexShrink: 0, width: 90, color: "#6b7280", fontSize: 12 },
  rowValue: { color: "#111827", wordBreak: "break-all", flex: 1 },
  code: {
    fontFamily: "monospace", fontSize: 12, background: "#f3f4f6",
    padding: "1px 5px", borderRadius: 3,
  },
  toggleBtn: {
    background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: 4,
    padding: "2px 8px", cursor: "pointer", fontSize: 11,
  },
  miniJson: {
    marginTop: 4, background: "#0f172a", color: "#e2e8f0",
    padding: 8, borderRadius: 5, fontSize: 11, fontFamily: "monospace",
    whiteSpace: "pre-wrap",
  },
  emptyBox: {
    background: "#fffbeb", border: "1px solid #fde68a", color: "#92400e",
    padding: "10px 12px", borderRadius: 5, fontSize: 12,
  },
  errorBox: {
    background: "#fef2f2", border: "1px solid #fca5a5", color: "#b91c1c",
    padding: "8px 12px", borderRadius: 5, fontSize: 12, marginBottom: 8,
  },
  refreshBtn: {
    background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: 5,
    padding: "4px 10px", cursor: "pointer", fontSize: 12, fontWeight: 600,
  },
  toolCard: {
    border: "1px solid #e5e7eb", borderRadius: 6, marginBottom: 6,
    background: "#fff", overflow: "hidden",
  },
  toolHeader: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "8px 12px", cursor: "pointer",
  },
  toolName: { fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: "#111827" },
  toolDesc: { fontSize: 11, color: "#6b7280", marginTop: 2 },
  toolChevron: { fontSize: 18, color: "#9ca3af", lineHeight: 1 },
  schemaBox: {
    margin: 0, background: "#0f172a", color: "#e2e8f0",
    padding: 10, fontSize: 11, fontFamily: "monospace",
    maxHeight: 220, overflow: "auto",
  },
  helpText: { fontSize: 12, color: "#6b7280" },
  usagesList: { margin: 0, paddingLeft: 18, fontSize: 13 },
  usageItem: { marginBottom: 4 },
  usageLink: {
    background: "none", border: "none", padding: 0, cursor: "pointer",
    color: "#2563eb", fontWeight: 600, textDecoration: "underline", fontSize: 13,
  },
  usageNode: { color: "#6b7280", fontSize: 11 },
};
