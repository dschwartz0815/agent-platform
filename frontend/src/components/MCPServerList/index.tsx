import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteMCPServer,
  getMCPServerUsages,
  listMCPServers,
  refreshMCPServerTools,
} from "../../api/client";
import { Modal } from "../shared/Modal";
import { UsageWarning } from "../shared/UsageWarning";
import { MCPServerFormModal } from "./MCPServerFormModal";
import { MCPServerDetailsDrawer } from "./MCPServerDetailsDrawer";
import type { MCPServer, Usage } from "../../types";

interface Props {
  onOpenGraph: (graphId: string) => void;
}

interface Banner {
  kind: "success" | "warn" | "error";
  text: string;
}

export function MCPServerList({ onOpenGraph }: Props) {
  const qc = useQueryClient();
  const { data: servers = [], isLoading } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: listMCPServers,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<MCPServer | null>(null);
  const [detailsFor, setDetailsFor] = useState<MCPServer | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<MCPServer | null>(null);
  const [deleteUsages, setDeleteUsages] = useState<Usage[] | null>(null);
  const [deleteAck, setDeleteAck] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);

  const openCreate = () => { setEditing(null); setFormOpen(true); };
  const openEdit = (s: MCPServer) => { setEditing(s); setFormOpen(true); };

  const refreshMut = useMutation({
    mutationFn: (id: string) => refreshMCPServerTools(id),
    onSuccess: (result, id) => {
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      const server = servers.find((s) => s.id === id);
      setBanner({
        kind: "success",
        text: `Refreshed "${server?.name ?? "server"}": ${result.tools.length} tool(s) discovered.`,
      });
    },
    onError: () => setBanner({
      kind: "error",
      text: "Refresh failed. The server may be unreachable, or (for stdio) the command is missing on the backend.",
    }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteMCPServer(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      setBanner({ kind: "success", text: `Deleted "${confirmDelete?.name ?? "server"}".` });
      setConfirmDelete(null);
      setDeleteUsages(null);
      setDeleteAck(false);
    },
    onError: () => setBanner({ kind: "error", text: "Delete failed." }),
  });

  const askDelete = async (s: MCPServer) => {
    setConfirmDelete(s);
    setDeleteAck(false);
    setDeleteUsages(null);
    try {
      const u = await getMCPServerUsages(s.id);
      setDeleteUsages(u);
    } catch {
      setDeleteUsages([]);
    }
  };

  if (isLoading) return <div style={styles.container}>Loading MCP servers…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>MCP Servers</h2>
        <button style={styles.newBtn} onClick={openCreate}>+ New MCP Server</button>
      </div>

      {banner && (
        <div style={{ ...styles.banner, ...bannerStyle(banner.kind) }}>
          <span>{banner.text}</span>
          <button style={styles.bannerClose} onClick={() => setBanner(null)}>×</button>
        </div>
      )}

      {servers.length === 0 && (
        <p style={{ color: "#6b7280" }}>
          No MCP servers registered yet. Click "+ New MCP Server" to register an HTTP or stdio server.
        </p>
      )}

      {servers.map((s) => {
        const toolCount = s.tools_json?.length ?? 0;
        const discovered = toolCount > 0;
        return (
          <div key={s.id} style={styles.card}>
            <div style={styles.cardBody}>
              <div style={styles.cardTitleRow}>
                <span style={styles.cardTitle}>{s.name}</span>
                <TransportBadge transport={s.transport} />
                <ToolsStatus discovered={discovered} count={toolCount} />
              </div>
              {s.description && <div style={styles.cardDesc}>{s.description}</div>}
              <div style={styles.cardMeta}>
                {s.transport === "http" && s.url && (
                  <code style={styles.codeMeta}>{s.url}</code>
                )}
                {s.transport === "stdio" && s.command && (
                  <code style={styles.codeMeta}>
                    {s.command} {(s.args ?? []).join(" ")}
                  </code>
                )}
                {" · "}
                {new Date(s.created_at).toLocaleDateString()}
              </div>
            </div>
            <div style={styles.cardActions}>
              <button style={styles.btn} onClick={() => setDetailsFor(s)}>Details</button>
              <button style={styles.btn} onClick={() => openEdit(s)}>Edit</button>
              <button
                style={styles.btn}
                onClick={() => refreshMut.mutate(s.id)}
                disabled={refreshMut.isPending && refreshMut.variables === s.id}
              >
                {refreshMut.isPending && refreshMut.variables === s.id ? "Refreshing…" : "Refresh"}
              </button>
              <button
                style={{ ...styles.btn, color: "#dc2626" }}
                onClick={() => askDelete(s)}
              >
                Delete
              </button>
            </div>
          </div>
        );
      })}

      <MCPServerFormModal
        open={formOpen}
        server={editing}
        onClose={() => setFormOpen(false)}
        onResult={({ server, mode, toolsDiscovered }) => {
          if (mode === "create") {
            setBanner({
              kind: toolsDiscovered && toolsDiscovered > 0 ? "success" : "warn",
              text: toolsDiscovered && toolsDiscovered > 0
                ? `Created "${server.name}". Discovered ${toolsDiscovered} tool(s).`
                : `Created "${server.name}". Tool discovery failed — click Refresh to retry.`,
            });
          } else {
            setBanner({ kind: "success", text: `Updated "${server.name}".` });
          }
        }}
      />

      <MCPServerDetailsDrawer
        open={Boolean(detailsFor)}
        server={detailsFor}
        onClose={() => setDetailsFor(null)}
        onOpenGraph={onOpenGraph}
      />

      <Modal
        open={Boolean(confirmDelete)}
        title="Delete MCP Server"
        onClose={() => { setConfirmDelete(null); setDeleteUsages(null); setDeleteAck(false); }}
        locked={deleteMut.isPending}
      >
        {confirmDelete && (
          <>
            <div style={{ fontSize: 13, marginBottom: 12 }}>
              Delete <strong>{confirmDelete.name}</strong>? This cannot be undone.
            </div>
            {deleteUsages === null ? (
              <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 12 }}>
                Checking for references…
              </div>
            ) : deleteUsages.length > 0 ? (
              <>
                <UsageWarning usages={deleteUsages} onOpenGraph={onOpenGraph} />
                <label style={styles.ackRow}>
                  <input
                    type="checkbox"
                    checked={deleteAck}
                    onChange={(e) => setDeleteAck(e.target.checked)}
                  />
                  <span style={{ fontSize: 12 }}>
                    I understand this will break the listed graphs.
                  </span>
                </label>
              </>
            ) : (
              <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 12 }}>
                Not referenced by any graph.
              </div>
            )}
            <div style={styles.modalActions}>
              <button
                style={styles.cancelBtn}
                onClick={() => { setConfirmDelete(null); setDeleteUsages(null); setDeleteAck(false); }}
                disabled={deleteMut.isPending}
              >
                Cancel
              </button>
              <button
                style={styles.deleteBtn}
                onClick={() => deleteMut.mutate(confirmDelete.id)}
                disabled={
                  deleteMut.isPending ||
                  deleteUsages === null ||
                  (deleteUsages.length > 0 && !deleteAck)
                }
              >
                {deleteMut.isPending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function TransportBadge({ transport }: { transport: string }) {
  const isHttp = transport === "http";
  return (
    <span style={{
      background: isHttp ? "#faf5ff" : "#fff7ed",
      color: isHttp ? "#7c3aed" : "#ea580c",
      border: `1px solid ${isHttp ? "#c4b5fd" : "#fdba74"}`,
      borderRadius: 4,
      padding: "1px 6px",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.05em",
    }}>
      {isHttp ? "HTTP" : "STDIO"}
    </span>
  );
}

function ToolsStatus({ discovered, count }: { discovered: boolean; count: number }) {
  return (
    <span style={{
      background: discovered ? "#f0fdf4" : "#fffbeb",
      color: discovered ? "#16a34a" : "#d97706",
      border: `1px solid ${discovered ? "#86efac" : "#fcd34d"}`,
      borderRadius: 4,
      padding: "1px 6px",
      fontSize: 10,
      fontWeight: 700,
    }}>
      {discovered ? `✓ ${count} tool${count === 1 ? "" : "s"}` : "⚠ tools missing"}
    </span>
  );
}

function bannerStyle(kind: Banner["kind"]): React.CSSProperties {
  switch (kind) {
    case "success": return { background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" };
    case "warn":    return { background: "#fffbeb", color: "#92400e", border: "1px solid #fcd34d" };
    case "error":   return { background: "#fef2f2", color: "#b91c1c", border: "1px solid #fca5a5" };
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: { padding: 24, maxWidth: 900, margin: "0 auto" },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: 16,
  },
  newBtn: {
    background: "#2563eb", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13,
  },
  banner: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "8px 12px", borderRadius: 5, fontSize: 12, marginBottom: 12,
  },
  bannerClose: {
    background: "none", border: "none", cursor: "pointer",
    fontSize: 16, lineHeight: 1, color: "inherit", opacity: 0.7,
  },
  card: {
    border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginBottom: 12,
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "#fff",
  },
  cardBody: { flex: 1, marginRight: 12, minWidth: 0 },
  cardTitleRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  cardTitle: { fontWeight: 600, fontSize: 15, color: "#111827" },
  cardDesc: { color: "#6b7280", fontSize: 13, marginTop: 3 },
  cardMeta: {
    color: "#9ca3af", fontSize: 12, marginTop: 5,
    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  },
  codeMeta: {
    fontFamily: "monospace", fontSize: 11, background: "#f3f4f6",
    padding: "1px 5px", borderRadius: 3, color: "#4b5563",
  },
  cardActions: { display: "flex", gap: 6, flexShrink: 0 },
  btn: {
    background: "#f3f4f6", border: "1px solid #d1d5db",
    borderRadius: 5, padding: "5px 10px", cursor: "pointer", fontSize: 12,
  },
  modalActions: {
    display: "flex", gap: 8, justifyContent: "flex-end",
    marginTop: 14, borderTop: "1px solid #e5e7eb", paddingTop: 14,
  },
  cancelBtn: {
    background: "#f3f4f6", border: "1px solid #d1d5db",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer",
    fontSize: 13, fontWeight: 600,
  },
  deleteBtn: {
    background: "#dc2626", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 20px", cursor: "pointer",
    fontSize: 13, fontWeight: 700,
  },
  ackRow: {
    display: "flex", alignItems: "center", gap: 6,
    marginTop: 10, marginBottom: 4, cursor: "pointer",
  },
};
