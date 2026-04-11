import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteApiKey, listApiKeys, revokeApiKey } from "../../api/client";
import { Modal } from "../shared/Modal";
import { ApiKeyFormModal } from "./ApiKeyFormModal";
import { RevealKeyModal } from "./RevealKeyModal";
import type { ApiKey, ApiKeyCreated } from "../../types";

interface Banner {
  kind: "success" | "warn" | "error";
  text: string;
}

export function ApiKeyList() {
  const qc = useQueryClient();
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [reveal, setReveal] = useState<ApiKeyCreated | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ kind: "revoke" | "delete"; key: ApiKey } | null>(null);
  const [banner, setBanner] = useState<Banner | null>(null);

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      setBanner({ kind: "success", text: "Key revoked." });
      setConfirmAction(null);
    },
    onError: () => setBanner({ kind: "error", text: "Revoke failed." }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteApiKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      setBanner({ kind: "success", text: "Key deleted." });
      setConfirmAction(null);
    },
    onError: () => setBanner({ kind: "error", text: "Delete failed." }),
  });

  if (isLoading) return <div style={styles.container}>Loading API keys…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>API Keys</h2>
        <button style={styles.newBtn} onClick={() => setFormOpen(true)}>
          + New Key
        </button>
      </div>

      <p style={styles.intro}>
        Keys authenticate calls to public run endpoints at{" "}
        <code style={styles.code}>POST /v1/run/{"{org}/{slug}"}</code>. Use{" "}
        <code style={styles.code}>Authorization: Bearer ap_live_...</code>.
      </p>

      {banner && (
        <div style={{ ...styles.banner, ...bannerStyle(banner.kind) }}>
          <span>{banner.text}</span>
          <button style={styles.bannerClose} onClick={() => setBanner(null)}>×</button>
        </div>
      )}

      {keys.length === 0 ? (
        <p style={{ color: "#6b7280" }}>
          No keys yet. Click "+ New Key" to create one.
        </p>
      ) : (
        keys.map((k) => (
          <div key={k.id} style={styles.card}>
            <div style={styles.cardBody}>
              <div style={styles.titleRow}>
                <span style={styles.keyName}>{k.name}</span>
                <ScopeBadge scopes={k.scopes} />
                {k.revoked_at && <span style={styles.revokedBadge}>REVOKED</span>}
              </div>
              <div style={styles.keyIdRow}>
                <code style={styles.prefix}>{k.key_prefix}</code>
                <span style={styles.dots}>…{k.key_last4}</span>
              </div>
              <div style={styles.meta}>
                Created {new Date(k.created_at).toLocaleDateString()}
                {" · "}
                {k.last_used_at
                  ? `last used ${new Date(k.last_used_at).toLocaleDateString()}`
                  : "never used"}
              </div>
            </div>
            <div style={styles.actions}>
              {!k.revoked_at && (
                <button
                  style={styles.btn}
                  onClick={() => setConfirmAction({ kind: "revoke", key: k })}
                >
                  Revoke
                </button>
              )}
              <button
                style={{ ...styles.btn, color: "#dc2626" }}
                onClick={() => setConfirmAction({ kind: "delete", key: k })}
              >
                Delete
              </button>
            </div>
          </div>
        ))
      )}

      <ApiKeyFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
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

      <Modal
        open={Boolean(confirmAction)}
        title={confirmAction?.kind === "revoke" ? "Revoke API Key" : "Delete API Key"}
        onClose={() => setConfirmAction(null)}
        locked={revokeMut.isPending || deleteMut.isPending}
      >
        {confirmAction && (
          <>
            <div style={{ fontSize: 13, marginBottom: 12 }}>
              {confirmAction.kind === "revoke" ? (
                <>
                  Revoke <strong>{confirmAction.key.name}</strong>? It will immediately
                  stop working. Existing runs that were started with this key will
                  complete, but no new calls will be accepted.
                </>
              ) : (
                <>
                  Delete <strong>{confirmAction.key.name}</strong>? This permanently
                  removes the row. Prefer <strong>Revoke</strong> if you want to
                  keep an audit trail.
                </>
              )}
            </div>
            <div style={styles.modalActions}>
              <button
                style={styles.cancelBtn}
                onClick={() => setConfirmAction(null)}
                disabled={revokeMut.isPending || deleteMut.isPending}
              >
                Cancel
              </button>
              <button
                style={styles.dangerBtn}
                onClick={() => {
                  if (confirmAction.kind === "revoke") {
                    revokeMut.mutate(confirmAction.key.id);
                  } else {
                    deleteMut.mutate(confirmAction.key.id);
                  }
                }}
                disabled={revokeMut.isPending || deleteMut.isPending}
              >
                {revokeMut.isPending || deleteMut.isPending
                  ? "Working…"
                  : confirmAction.kind === "revoke" ? "Revoke" : "Delete"}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function ScopeBadge({ scopes }: { scopes: string[] }) {
  const isWild = scopes.includes("*");
  return (
    <span style={{
      background: isWild ? "#fef3c7" : "#dbeafe",
      color: isWild ? "#92400e" : "#1e40af",
      border: `1px solid ${isWild ? "#fcd34d" : "#bfdbfe"}`,
      borderRadius: 4,
      padding: "1px 7px",
      fontSize: 10,
      fontWeight: 700,
    }}>
      {isWild ? "ALL GRAPHS" : `${scopes.length} SCOPE${scopes.length === 1 ? "" : "S"}`}
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
    marginBottom: 12,
  },
  newBtn: {
    background: "#2563eb", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13,
  },
  intro: {
    fontSize: 13,
    color: "#4b5563",
    marginBottom: 16,
    lineHeight: 1.5,
  },
  code: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#374151",
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
  titleRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  keyName: { fontWeight: 600, fontSize: 15, color: "#111827" },
  revokedBadge: {
    background: "#fef2f2",
    color: "#dc2626",
    border: "1px solid #fca5a5",
    borderRadius: 4,
    padding: "1px 7px",
    fontSize: 10,
    fontWeight: 700,
  },
  keyIdRow: { display: "flex", alignItems: "center", gap: 4, marginTop: 4 },
  prefix: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
    color: "#374151",
  },
  dots: { fontFamily: "monospace", fontSize: 12, color: "#9ca3af" },
  meta: { color: "#9ca3af", fontSize: 12, marginTop: 5 },
  actions: { display: "flex", gap: 6, flexShrink: 0 },
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
  dangerBtn: {
    background: "#dc2626", color: "#fff", border: "none",
    borderRadius: 6, padding: "8px 20px", cursor: "pointer",
    fontSize: 13, fontWeight: 700,
  },
};
