import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { publishGraph } from "../../api/client";
import { Modal } from "../shared/Modal";

interface Props {
  open: boolean;
  graphId: string;
  nextVersion: number;
  onClose: () => void;
}

export function PublishModal({ open, graphId, nextVersion, onClose }: Props) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const publishMut = useMutation({
    mutationFn: () => publishGraph(graphId, { notes: notes.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graphId] });
      qc.invalidateQueries({ queryKey: ["graph-versions", graphId] });
      setNotes("");
      setError(null);
      onClose();
    },
    onError: (err: unknown) => {
      const resp = (err as { response?: { data?: { error?: string; detail?: string } } }).response;
      setError(resp?.data?.error ?? resp?.data?.detail ?? "Publish failed");
    },
  });

  return (
    <Modal
      open={open}
      title={`Publish v${nextVersion}`}
      onClose={onClose}
      locked={publishMut.isPending}
    >
      <div style={{ fontSize: 13, marginBottom: 12, color: "#374151" }}>
        This will freeze the current draft as <strong>v{nextVersion}</strong>. The version is
        immutable — you won't be able to change it later. Future edits will go into a new draft.
      </div>

      <label style={styles.label}>Release notes (optional)</label>
      <textarea
        style={styles.textarea}
        placeholder="What changed in this version?"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        disabled={publishMut.isPending}
      />

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.actions}>
        <button
          style={styles.cancelBtn}
          onClick={onClose}
          disabled={publishMut.isPending}
        >
          Cancel
        </button>
        <button
          style={styles.publishBtn}
          onClick={() => publishMut.mutate()}
          disabled={publishMut.isPending}
        >
          {publishMut.isPending ? "Publishing…" : `Publish v${nextVersion}`}
        </button>
      </div>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  label: {
    display: "block",
    fontSize: 11,
    fontWeight: 600,
    color: "#374151",
    marginBottom: 4,
  },
  textarea: {
    width: "100%",
    minHeight: 80,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    fontFamily: "system-ui, sans-serif",
    boxSizing: "border-box",
    resize: "vertical",
  },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    borderRadius: 5,
    padding: "8px 12px",
    fontSize: 12,
    marginTop: 10,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    marginTop: 14,
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
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
  publishBtn: {
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
