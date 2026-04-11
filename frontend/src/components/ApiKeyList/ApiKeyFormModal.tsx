import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createApiKey, listGraphs } from "../../api/client";
import { Modal } from "../shared/Modal";
import type { ApiKeyCreated, ApiKeyCreate } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Optional: if provided, pre-select this graph in the scope and lock wildcard off */
  preScopedGraphId?: string;
  /** Called with the plaintext-bearing response when the key is created */
  onCreated: (created: ApiKeyCreated) => void;
}

export function ApiKeyFormModal({ open, onClose, preScopedGraphId, onCreated }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [wildcard, setWildcard] = useState(!preScopedGraphId);
  const [selectedGraphIds, setSelectedGraphIds] = useState<string[]>(
    preScopedGraphId ? [preScopedGraphId] : []
  );
  const [error, setError] = useState<string | null>(null);

  const { data: graphs = [] } = useQuery({
    queryKey: ["graphs"],
    queryFn: listGraphs,
    enabled: open,
  });

  useEffect(() => {
    if (open) {
      setName("");
      setWildcard(!preScopedGraphId);
      setSelectedGraphIds(preScopedGraphId ? [preScopedGraphId] : []);
      setError(null);
    }
  }, [open, preScopedGraphId]);

  const createMut = useMutation({
    mutationFn: (body: ApiKeyCreate) => createApiKey(body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      onCreated(created);
    },
    onError: (err: unknown) => {
      const resp = (err as { response?: { data?: { error?: string; detail?: string } } }).response;
      setError(resp?.data?.error ?? resp?.data?.detail ?? "Create failed");
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const scopes = wildcard ? ["*"] : selectedGraphIds;
    if (!wildcard && scopes.length === 0) {
      setError("Select at least one graph or choose 'All graphs'");
      return;
    }
    createMut.mutate({ name: name.trim(), scopes });
  };

  const toggleGraph = (id: string) => {
    setSelectedGraphIds((prev) =>
      prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
    );
  };

  return (
    <Modal
      open={open}
      title="New API Key"
      onClose={onClose}
      locked={createMut.isPending}
      maxWidth={520}
    >
      <form onSubmit={submit}>
        <div style={styles.field}>
          <label style={styles.label}>Name</label>
          <input
            style={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={createMut.isPending}
            placeholder="e.g. Staging pipeline"
            autoFocus
          />
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Scope</label>
          <label style={styles.radioRow}>
            <input
              type="radio"
              checked={wildcard}
              onChange={() => setWildcard(true)}
              disabled={createMut.isPending || Boolean(preScopedGraphId)}
            />
            <span style={{ fontSize: 13 }}>All graphs (*)</span>
          </label>
          <label style={styles.radioRow}>
            <input
              type="radio"
              checked={!wildcard}
              onChange={() => setWildcard(false)}
              disabled={createMut.isPending}
            />
            <span style={{ fontSize: 13 }}>Specific graphs</span>
          </label>
          {!wildcard && (
            <div style={styles.graphList}>
              {graphs.length === 0 && (
                <div style={{ color: "#9ca3af", fontSize: 12 }}>No graphs to pick.</div>
              )}
              {graphs.map((g) => (
                <label key={g.id} style={styles.graphRow}>
                  <input
                    type="checkbox"
                    checked={selectedGraphIds.includes(g.id)}
                    onChange={() => toggleGraph(g.id)}
                    disabled={createMut.isPending}
                  />
                  <span style={{ fontSize: 13 }}>{g.name}</span>
                  {g.slug && (
                    <code style={styles.slug}>{g.slug}</code>
                  )}
                </label>
              ))}
            </div>
          )}
          {preScopedGraphId && !wildcard && (
            <div style={styles.hint}>Pre-selected for the current graph.</div>
          )}
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.actions}>
          <button
            type="button"
            style={styles.cancelBtn}
            onClick={onClose}
            disabled={createMut.isPending}
          >
            Cancel
          </button>
          <button
            type="submit"
            style={styles.submitBtn}
            disabled={createMut.isPending}
          >
            {createMut.isPending ? "Creating…" : "Create key"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  field: { marginBottom: 14 },
  label: {
    display: "block",
    fontSize: 11,
    fontWeight: 700,
    color: "#374151",
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
    cursor: "pointer",
  },
  graphList: {
    marginTop: 6,
    padding: 8,
    border: "1px solid #e5e7eb",
    borderRadius: 5,
    maxHeight: 180,
    overflowY: "auto",
  },
  graphRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "3px 0",
    cursor: "pointer",
  },
  slug: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#6b7280",
    marginLeft: "auto",
  },
  hint: { fontSize: 11, color: "#6b7280", marginTop: 4 },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
    marginBottom: 12,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
    marginTop: 6,
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  submitBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
  },
};
