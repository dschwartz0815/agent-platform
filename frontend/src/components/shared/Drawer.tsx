import { useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** Width of the drawer in pixels. Default 520. */
  width?: number;
}

/**
 * Right-side slide-over drawer. No animation; just a fixed-width panel
 * anchored to the right edge with a semi-transparent backdrop on the left.
 */
export function Drawer({ open, title, onClose, children, width = 520 }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div
        style={{ ...styles.panel, width }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={styles.header}>
          <h3 style={styles.title}>{title}</h3>
          <button
            style={styles.closeBtn}
            onClick={onClose}
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
    background: "rgba(15, 23, 42, 0.35)",
    zIndex: 90,
    display: "flex",
    justifyContent: "flex-end",
  },
  panel: {
    height: "100vh",
    background: "#fff",
    boxShadow: "-8px 0 24px rgba(0,0,0,0.12)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "14px 20px",
    borderBottom: "1px solid #e5e7eb",
    flexShrink: 0,
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
    flex: 1,
    overflowY: "auto",
    padding: 20,
  },
};
