import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { GraphList } from "./components/GraphList";
import { GraphEditor } from "./components/GraphEditor";
import { GraphDetail } from "./components/GraphDetail";
import { AgentList } from "./components/AgentList";
import { MCPServerList } from "./components/MCPServerList";
import { ApiKeyList } from "./components/ApiKeyList";
import { Catalog } from "./components/Catalog";
import { WorkspaceSettings } from "./components/WorkspaceSettings";
import { getMe } from "./api/client";
import { getActiveWorkspaceId, setActiveWorkspaceId } from "./identity";
import type { Me, Workspace } from "./types";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

type View = "studio" | "agents" | "tools" | "catalog" | "api-keys" | "settings";

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  );
}

function Shell() {
  const [view, setView] = useState<View>("studio");
  const [detailGraphId, setDetailGraphId] = useState<string | null>(null);
  const [editorGraphId, setEditorGraphId] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: me, isLoading, isError } = useQuery({ queryKey: ["me"], queryFn: getMe });

  const workspaces = me?.workspaces ?? [];
  const activeId = getActiveWorkspaceId();
  const activeWorkspace: Workspace | undefined =
    workspaces.find((w) => w.id === activeId) ?? workspaces[0];

  // Keep the stored selection valid (e.g. after a group change removed access)
  if (activeWorkspace && activeWorkspace.id !== activeId) {
    setActiveWorkspaceId(activeWorkspace.id);
  }

  const switchWorkspace = (id: string) => {
    setActiveWorkspaceId(id);
    setDetailGraphId(null);
    setEditorGraphId(null);
    qc.clear(); // every cached query is tenant-scoped
  };

  const openGraphDetail = (id: string) => {
    setDetailGraphId(id);
    setEditorGraphId(null);
    setView("studio");
  };

  if (isLoading) {
    return <div style={styles.fullPage}>Loading…</div>;
  }
  if (isError || !me) {
    return (
      <div style={styles.fullPage}>
        Could not resolve your identity. Is the backend running?
      </div>
    );
  }

  const body = !activeWorkspace ? (
    <NoWorkspace me={me} onCreated={() => qc.invalidateQueries({ queryKey: ["me"] })} />
  ) : editorGraphId ? (
    <GraphEditor graphId={editorGraphId} onBack={() => setEditorGraphId(null)} />
  ) : detailGraphId ? (
    <GraphDetail
      graphId={detailGraphId}
      onBack={() => setDetailGraphId(null)}
      onEdit={(id) => setEditorGraphId(id)}
    />
  ) : (
    <>
      {view === "studio" && <GraphList onOpen={openGraphDetail} />}
      {view === "agents" && <AgentList onOpenGraph={openGraphDetail} />}
      {view === "tools" && <MCPServerList onOpenGraph={openGraphDetail} />}
      {view === "catalog" && <Catalog workspace={activeWorkspace} />}
      {view === "api-keys" && <ApiKeyList />}
      {view === "settings" && <WorkspaceSettings me={me} workspace={activeWorkspace} />}
    </>
  );

  const inSubPage = Boolean(editorGraphId || detailGraphId);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", background: "#f9fafb", minHeight: "100vh" }}>
      {!inSubPage && (
        <Header
          view={view}
          onChange={setView}
          me={me}
          activeWorkspace={activeWorkspace}
          onSwitchWorkspace={switchWorkspace}
        />
      )}
      {body}
    </div>
  );
}

function Header({
  view,
  onChange,
  me,
  activeWorkspace,
  onSwitchWorkspace,
}: {
  view: View;
  onChange: (v: View) => void;
  me: Me;
  activeWorkspace: Workspace | undefined;
  onSwitchWorkspace: (id: string) => void;
}) {
  const tabs: { id: View; label: string }[] = [
    { id: "studio",   label: "Studio" },
    { id: "agents",   label: "Agents" },
    { id: "tools",    label: "Tools" },
    { id: "catalog",  label: "Catalog" },
    { id: "api-keys", label: "API Keys" },
    { id: "settings", label: "Settings" },
  ];
  return (
    <div style={styles.header}>
      <div style={styles.brand}>
        <span style={styles.brandName}>Agent Platform</span>
        {activeWorkspace && (
          <select
            style={styles.wsSelect}
            value={activeWorkspace.id}
            onChange={(e) => onSwitchWorkspace(e.target.value)}
            title="Active workspace (derived from your AD groups)"
          >
            {me.workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {w.role}
              </option>
            ))}
          </select>
        )}
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
      <div style={styles.userChip} title={`AD groups: ${me.ad_groups.join(", ") || "none"}`}>
        {me.display_name}
      </div>
    </div>
  );
}

function NoWorkspace({ me, onCreated }: { me: Me; onCreated: () => void }) {
  return (
    <div style={{ maxWidth: 640, margin: "60px auto", padding: 24 }}>
      <h2>No workspace access</h2>
      <p style={{ color: "#6b7280", lineHeight: 1.6 }}>
        Signed in as <b>{me.email}</b> with AD groups{" "}
        {me.ad_groups.length ? <code>{me.ad_groups.join(", ")}</code> : <i>(none)</i>}.
        None of your AD groups are mapped to a workspace. Ask a workspace admin to map
        one of your groups under <b>Settings → Group mappings</b>, or create a new
        workspace anchored to one of your groups.
      </p>
      <WorkspaceSettings me={me} workspace={null} onWorkspaceCreated={onCreated} />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  fullPage: {
    fontFamily: "system-ui, sans-serif",
    padding: 48,
    color: "#6b7280",
  },
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
    gap: 12,
  },
  brandName: {
    fontWeight: 800,
    fontSize: 18,
    letterSpacing: "-0.02em",
  },
  wsSelect: {
    background: "#334155",
    color: "#fff",
    border: "1px solid #475569",
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 13,
    fontFamily: "inherit",
  },
  tabs: {
    display: "flex",
    gap: 4,
    flex: 1,
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
  userChip: {
    fontSize: 13,
    color: "#cbd5e1",
    background: "#334155",
    borderRadius: 999,
    padding: "4px 12px",
  },
};
