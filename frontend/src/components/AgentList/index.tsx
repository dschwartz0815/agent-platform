import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteAgent,
  getAgentUsages,
  listAgents,
  refreshAgentCard,
} from "../../api/client";
import { Modal } from "../shared/Modal";
import { UsageWarning } from "../shared/UsageWarning";
import { AgentFormModal } from "./AgentFormModal";
import { AgentDetailsDrawer } from "./AgentDetailsDrawer";
import type { Agent, Usage } from "../../types";

interface Props {
  onOpenGraph: (graphId: string) => void;
}

interface Banner {
  kind: "success" | "warn" | "error";
  text: string;
}

export function AgentList({ onOpenGraph }: Props) {
  const qc = useQueryClient();
  const { data: agents = [], isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [detailsFor, setDetailsFor] = useState<Agent | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Agent | null>(null);
  const [deleteUsages, setDeleteUsages] = useState<Usage[] | null>(null);
  const [deleteAck, setDeleteAck] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (a: Agent) => {
    setEditing(a);
    setFormOpen(true);
  };

  const refreshMut = useMutation({
    mutationFn: (id: string) => refreshAgentCard(id),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setBanner({
        kind: updated.agent_card_json ? "success" : "warn",
        text: updated.agent_card_json
          ? `Refreshed "${updated.name}": agent card fetched.`
          : `Refreshed "${updated.name}": card still unavailable.`,
      });
    },
    onError: () => setBanner({ kind: "error", text: "Refresh failed. The agent may be unreachable." }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteAgent(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setBanner({ kind: "success", text: `Deleted "${confirmDelete?.name ?? "agent"}".` });
      setConfirmDelete(null);
      setDeleteUsages(null);
      setDeleteAck(false);
    },
    onError: () => setBanner({ kind: "error", text: "Delete failed." }),
  });

  const askDelete = async (a: Agent) => {
    setConfirmDelete(a);
    setDeleteAck(false);
    setDeleteUsages(null);
    try {
      const u = await getAgentUsages(a.id);
      setDeleteUsages(u);
    } catch {
      setDeleteUsages([]); // fall through, assume safe
    }
  };

  if (isLoading) return <div style={styles.container}>Loading agents…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>Agents</h2>
        <button style={styles.newBtn} onClick={openCreate}>+ New Agent</button>
      </div>

      {banner && (
        <div style={{ ...styles.banner, ...bannerStyle(banner.kind) }}>
          <span>{banner.text}</span>
          <button style={styles.bannerClose} onClick={() => setBanner(null)}>×</button>
        </div>
      )}

      {agents.length === 0 && (
        <p style={{ color: "#6b7280" }}>
          No agents registered yet. Click "+ New Agent" to register an LLM or A2A HTTP agent.
        </p>
      )}

      {agents.map((a) => (
        <div key={a.id} style={styles.card}>
          <div style={styles.cardBody}>
            <div style={styles.cardTitleRow}>
              <span style={styles.cardTitle}>{a.name}</span>
              <TypeBadge type={a.agent_type} />
              {a.agent_type === "http" && <CardStatus fetched={Boolean(a.agent_card_json)} />}
            </div>
            {a.description && <div style={styles.cardDesc}>{a.description}</div>}
            <div style={styles.cardMeta}>
              {a.agent_type === "llm" && a.model && (
                <code style={styles.codeMeta}>{a.model}</code>
              )}
              {a.agent_type === "http" && a.url && (
                <code style={styles.codeMeta}>{a.url}</code>
              )}
              {" · "}
              {new Date(a.created_at).toLocaleDateString()}
            </div>
          </div>
          <div style={styles.cardActions}>
            <button style={styles.btn} onClick={() => setDetailsFor(a)}>Details</button>
            <button style={styles.btn} onClick={() => openEdit(a)}>Edit</button>
            {a.agent_type === "http" && (
              <button
                style={styles.btn}
                onClick={() => refreshMut.mutate(a.id)}
                disabled={refreshMut.isPending && refreshMut.variables === a.id}
              >
                {refreshMut.isPending && refreshMut.variables === a.id ? "Refreshing…" : "Refresh"}
              </button>
            )}
            <button
              style={{ ...styles.btn, color: "#dc2626" }}
              onClick={() => askDelete(a)}
            >
              Delete
            </button>
          </div>
        </div>
      ))}

      {/* Create/Edit modal */}
      <AgentFormModal
        open={formOpen}
        agent={editing}
        onClose={() => setFormOpen(false)}
        onResult={({ agent, mode, cardFetched }) => {
          if (mode === "create") {
            if (agent.agent_type === "http") {
              setBanner({
                kind: cardFetched ? "success" : "warn",
                text: cardFetched
                  ? `Created "${agent.name}". Agent card fetched.`
                  : `Created "${agent.name}". Could not fetch agent card — click Refresh to retry.`,
              });
            } else {
              setBanner({ kind: "success", text: `Created "${agent.name}".` });
            }
          } else {
            setBanner({ kind: "success", text: `Updated "${agent.name}".` });
          }
        }}
      />

      {/* Details drawer */}
      <AgentDetailsDrawer
        open={Boolean(detailsFor)}
        agent={detailsFor}
        onClose={() => setDetailsFor(null)}
        onOpenGraph={onOpenGraph}
      />

      {/* Delete confirmation modal */}
      <Modal
        open={Boolean(confirmDelete)}
        title="Delete Agent"
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

function TypeBadge({ type }: { type: string }) {
  const isLlm = type === "llm";
  return (
    <span style={{
      background: isLlm ? "#eff6ff" : "#ecfeff",
      color: isLlm ? "#2563eb" : "#0891b2",
      border: `1px solid ${isLlm ? "#bfdbfe" : "#a5f3fc"}`,
      borderRadius: 4,
      padding: "1px 6px",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.05em",
    }}>
      {isLlm ? "LLM" : "A2A"}
    </span>
  );
}

function CardStatus({ fetched }: { fetched: boolean }) {
  return (
    <span style={{
      background: fetched ? "#f0fdf4" : "#fffbeb",
      color: fetched ? "#16a34a" : "#d97706",
      border: `1px solid ${fetched ? "#86efac" : "#fcd34d"}`,
      borderRadius: 4,
      padding: "1px 6px",
      fontSize: 10,
      fontWeight: 700,
    }}>
      {fetched ? "✓ card fetched" : "⚠ card missing"}
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
  cardBody: { flex: 1, marginRight: 12 },
  cardTitleRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  cardTitle: { fontWeight: 600, fontSize: 15, color: "#111827" },
  cardDesc: { color: "#6b7280", fontSize: 13, marginTop: 3 },
  cardMeta: { color: "#9ca3af", fontSize: 12, marginTop: 5 },
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
    marginTop: 10, marginBottom: 4,
    cursor: "pointer",
  },
};
