import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GraphList } from "./components/GraphList";
import { GraphEditor } from "./components/GraphEditor";
import { GraphDetail } from "./components/GraphDetail";
import { AgentList } from "./components/AgentList";
import { MCPServerList } from "./components/MCPServerList";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

type View = "graphs" | "agents" | "mcp-servers";

export default function App() {
  const [view, setView] = useState<View>("graphs");
  const [detailGraphId, setDetailGraphId] = useState<string | null>(null);
  const [editorGraphId, setEditorGraphId] = useState<string | null>(null);

  const openGraphDetail = (id: string) => {
    setDetailGraphId(id);
    setEditorGraphId(null);
    setView("graphs");
  };

  const openGraphEditor = (id: string) => {
    setEditorGraphId(id);
  };

  const backFromEditor = () => {
    setEditorGraphId(null);
    // detailGraphId stays set → we return to the detail page
  };

  const backFromDetail = () => {
    setDetailGraphId(null);
  };

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ fontFamily: "system-ui, sans-serif", background: "#f9fafb", minHeight: "100vh" }}>
        {editorGraphId ? (
          <GraphEditor graphId={editorGraphId} onBack={backFromEditor} />
        ) : detailGraphId ? (
          <GraphDetail
            graphId={detailGraphId}
            onBack={backFromDetail}
            onEdit={openGraphEditor}
          />
        ) : (
          <>
            <Header view={view} onChange={setView} />
            {view === "graphs" && <GraphList onOpen={openGraphDetail} />}
            {view === "agents" && <AgentList onOpenGraph={openGraphDetail} />}
            {view === "mcp-servers" && <MCPServerList onOpenGraph={openGraphDetail} />}
          </>
        )}
      </div>
    </QueryClientProvider>
  );
}

function Header({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const tabs: { id: View; label: string }[] = [
    { id: "graphs",      label: "Graphs" },
    { id: "agents",      label: "Agents" },
    { id: "mcp-servers", label: "MCP Servers" },
  ];
  return (
    <div style={styles.header}>
      <div style={styles.brand}>
        <span style={styles.brandName}>Agent Platform</span>
        <span style={styles.brandDemo}>demo</span>
      </div>
      <nav style={styles.tabs}>
        {tabs.map((t) => (
          <button
            key={t.id}
            style={{ ...styles.tab, ...(view === t.id ? styles.tabActive : {}) }}
            onClick={() => onChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    background: "#1e293b",
    color: "#fff",
    padding: "12px 24px",
    display: "flex",
    alignItems: "center",
    gap: 24,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  brandName: {
    fontWeight: 800,
    fontSize: 18,
    letterSpacing: "-0.02em",
  },
  brandDemo: {
    color: "#94a3b8",
    fontSize: 13,
  },
  tabs: {
    display: "flex",
    gap: 4,
  },
  tab: {
    background: "transparent",
    color: "#cbd5e1",
    border: "none",
    padding: "6px 14px",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    fontFamily: "inherit",
  },
  tabActive: {
    background: "#334155",
    color: "#fff",
  },
};
