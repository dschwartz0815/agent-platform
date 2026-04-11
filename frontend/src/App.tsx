import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GraphList } from "./components/GraphList";
import { GraphEditor } from "./components/GraphEditor";
import { AgentList } from "./components/AgentList";
import { MCPServerList } from "./components/MCPServerList";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

type View = "graphs" | "agents" | "mcp-servers";

export default function App() {
  const [view, setView] = useState<View>("graphs");
  const [openGraphId, setOpenGraphId] = useState<string | null>(null);

  const openGraph = (id: string) => {
    setOpenGraphId(id);
    setView("graphs");
  };

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ fontFamily: "system-ui, sans-serif", background: "#f9fafb", minHeight: "100vh" }}>
        {openGraphId ? (
          <GraphEditor graphId={openGraphId} onBack={() => setOpenGraphId(null)} />
        ) : (
          <>
            <Header view={view} onChange={setView} />
            {view === "graphs" && <GraphList onOpen={openGraph} />}
            {view === "agents" && <AgentList onOpenGraph={openGraph} />}
            {view === "mcp-servers" && <MCPServerList onOpenGraph={openGraph} />}
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
