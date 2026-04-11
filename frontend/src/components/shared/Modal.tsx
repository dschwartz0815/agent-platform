import { useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  /** When true, Escape and backdrop click are disabled — use while a mutation is in flight. */
  locked?: boolean;
  children: React.ReactNode;
  /** Max width of the card in pixels. Default 480. */
  maxWidth?: number;
}

/**
 * Lightweight centered modal overlay. No animation, no library.
 * Locks body scroll while open and honors the Escape key unless `locked` is true.
 */
export function Modal({ open, title, onClose, locked = false, children, maxWidth = 480 }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked) onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, locked, onClose]);

  if (!open) return null;

  return (
    <div
      style={styles.backdrop}
      onClick={() => { if (!locked) onClose(); }}
    >
      <div
        style={{ ...styles.card, maxWidth }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={styles.header}>
          <h3 style={styles.title}>{title}</h3>
          <button
            style={styles.closeBtn}
            onClick={onClose}
            disabled={locked}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div style={styles.body}>{children}</div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  backdrop: {
    position: "fixed",
    inset: 0,
    background: "rgba(15, 23, 42, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 100,
    padding: 16,
  },
  card: {
    width: "100%",
    background: "#fff",
    borderRadius: 10,
    boxShadow: "0 20px 40px rgba(0,0,0,0.2)",
    display: "flex",
    flexDirection: "column",
    maxHeight: "90vh",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "14px 20px",
    borderBottom: "1px solid #e5e7eb",
  },
  title: {
    margin: 0,
    fontSize: 16,
    fontWeight: 700,
    color: "#111827",
  },
  closeBtn: {
    background: "none",
    border: "none",
    fontSize: 24,
    lineHeight: 1,
    cursor: "pointer",
    color: "#6b7280",
    padding: "0 4px",
  },
  body: {
    padding: 20,
    overflowY: "auto",
    flex: 1,
  },
};
