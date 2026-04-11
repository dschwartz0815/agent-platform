import { useState } from "react";
import { Modal } from "../shared/Modal";
import type { ApiKeyCreated } from "../../types";

interface Props {
  open: boolean;
  created: ApiKeyCreated | null;
  onClose: () => void;
}

export function RevealKeyModal({ open, created, onClose }: Props) {
  const [copied, setCopied] = useState(false);

  if (!created) return null;

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may not be available in insecure contexts
    }
  };

  return (
    <Modal
      open={open}
      title="Save your API key now"
      onClose={onClose}
      maxWidth={560}
    >
      <div style={styles.warn}>
        ⚠ <strong>You won't see this key again.</strong> Copy it now and store it
        somewhere safe. If you lose it, you'll need to create a new one.
      </div>

      <div style={styles.meta}>
        <div style={styles.metaRow}>
          <span style={styles.metaLabel}>Name</span>
          <span>{created.name}</span>
        </div>
        <div style={styles.metaRow}>
          <span style={styles.metaLabel}>Scope</span>
          <span>
            {created.scopes.includes("*")
              ? "All graphs"
              : `${created.scopes.length} graph${created.scopes.length === 1 ? "" : "s"}`}
          </span>
        </div>
      </div>

      <div style={styles.keyLabel}>Your API key</div>
      <div style={styles.keyBox}>
        <code style={styles.key}>{created.key}</code>
      </div>

      <div style={styles.actions}>
        <button
          style={styles.copyBtn}
          onClick={copyKey}
        >
          {copied ? "✓ Copied" : "📋 Copy key"}
        </button>
        <button style={styles.doneBtn} onClick={onClose}>
          I've saved it
        </button>
      </div>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  warn: {
    background: "#fffbeb",
    border: "1px solid #fcd34d",
    color: "#78350f",
    borderRadius: 6,
    padding: "10px 14px",
    fontSize: 13,
    marginBottom: 16,
    lineHeight: 1.5,
  },
  meta: {
    marginBottom: 14,
  },
  metaRow: {
    display: "flex",
    gap: 12,
    padding: "4px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  metaLabel: {
    width: 80,
    color: "#6b7280",
    fontSize: 12,
  },
  keyLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 6,
  },
  keyBox: {
    background: "#0f172a",
    borderRadius: 6,
    padding: 14,
    marginBottom: 14,
    overflowX: "auto",
  },
  key: {
    color: "#86efac",
    fontFamily: "monospace",
    fontSize: 13,
    wordBreak: "break-all",
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
  },
  copyBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  doneBtn: {
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
