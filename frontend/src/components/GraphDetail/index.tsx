import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getGraph } from "../../api/client";
import type { Graph } from "../../types";
import { OverviewTab } from "./OverviewTab";
import { VersionsTab } from "./VersionsTab";
import { PublishModal } from "./PublishModal";
import { APIDocsTab } from "./APIDocsTab";
import { RunsTab } from "./RunsTab";
import { TestTab } from "./TestTab";
import { KeysTab } from "./KeysTab";

type Tab = "overview" | "api-docs" | "versions" | "keys" | "runs" | "test";

interface Props {
  graphId: string;
  onBack: () => void;
  onEdit: (graphId: string) => void;
}

const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs" },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys" },
  { id: "runs", label: "Runs" },
  { id: "test", label: "Test" },
];

export function GraphDetail({ graphId, onBack, onEdit }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [publishOpen, setPublishOpen] = useState(false);

  const { data: graph, isLoading } = useQuery<Graph>({
    queryKey: ["graph", graphId],
    queryFn: () => getGraph(graphId),
  });

  if (isLoading) return <div style={{ padding: 24 }}>Loading…</div>;
  if (!graph) return <div style={{ padding: 24 }}>Graph not found.</div>;

  const nextVersion = (graph.latest_version_number ?? 0) + 1;
  const hasNodes = (graph.nodes?.length ?? 0) > 0;
  const canPublish = hasNodes;

  return (
    <div style={{ background: "#f9fafb", minHeight: "100vh" }}>
      <div style={styles.header}>
        <div style={styles.headerTop}>
          <button style={styles.backBtn} onClick={onBack}>← Graphs</button>
          <div style={styles.titleBlock}>
            <div style={styles.pathRow}>
              <code style={styles.path}>acme / {graph.slug ?? "untitled"}</code>
              {graph.latest_version_number && (
                <span style={styles.versionBadge}>v{graph.latest_version_number}</span>
              )}
            </div>
            <h1 style={styles.title}>{graph.name}</h1>
            {graph.description && <p style={styles.description}>{graph.description}</p>}
          </div>
          <div style={styles.actions}>
            <button style={styles.actionBtn} onClick={() => onEdit(graph.id)}>
              ✎ Edit
            </button>
            <button
              style={styles.publishBtn}
              onClick={() => setPublishOpen(true)}
              disabled={!canPublish}
              title={canPublish ? "" : "Add at least one node to publish"}
            >
              Publish v{nextVersion}
            </button>
          </div>
        </div>

        <nav style={styles.tabBar}>
          {TABS.map((t) => (
            <button
              key={t.id}
              style={{
                ...styles.tab,
                ...(activeTab === t.id ? styles.tabActive : {}),
                ...(t.disabled ? styles.tabDisabled : {}),
              }}
              onClick={() => !t.disabled && setActiveTab(t.id)}
              disabled={t.disabled}
            >
              {t.label}
              {t.disabled && <span style={styles.soon}> (soon)</span>}
            </button>
          ))}
        </nav>
      </div>

      <div style={styles.content}>
        {activeTab === "overview" && <OverviewTab graph={graph} />}
        {activeTab === "api-docs" && <APIDocsTab graph={graph} />}
        {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
        {activeTab === "keys" && <KeysTab graphId={graph.id} />}
        {activeTab === "runs" && <RunsTab graphId={graph.id} />}
        {activeTab === "test" && <TestTab graph={graph} />}
      </div>

      <PublishModal
        open={publishOpen}
        graphId={graph.id}
        nextVersion={nextVersion}
        onClose={() => setPublishOpen(false)}
      />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: { background: "#fff", borderBottom: "1px solid #e5e7eb" },
  headerTop: {
    display: "flex",
    alignItems: "flex-start",
    padding: "16px 24px 12px",
    gap: 16,
    maxWidth: 1200,
    margin: "0 auto",
    width: "100%",
    boxSizing: "border-box",
  },
  backBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#2563eb",
    fontWeight: 600,
    fontSize: 14,
    marginTop: 4,
  },
  titleBlock: { flex: 1 },
  pathRow: { display: "flex", alignItems: "center", gap: 8 },
  path: {
    fontFamily: "monospace",
    fontSize: 12,
    color: "#4b5563",
    background: "#f3f4f6",
    padding: "2px 8px",
    borderRadius: 4,
  },
  versionBadge: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    color: "#374151",
    fontSize: 11,
    fontWeight: 700,
    padding: "1px 7px",
    borderRadius: 3,
  },
  title: { margin: "6px 0 3px", fontSize: 22, fontWeight: 700, color: "#111827" },
  description: { margin: 0, color: "#4b5563", fontSize: 13 },
  actions: { display: "flex", gap: 8, flexShrink: 0 },
  actionBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "6px 14px",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 13,
  },
  publishBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "6px 16px",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
  },
  tabBar: {
    display: "flex",
    gap: 2,
    padding: "0 24px",
    maxWidth: 1200,
    margin: "0 auto",
    width: "100%",
    boxSizing: "border-box",
  },
  tab: {
    background: "none",
    border: "none",
    padding: "10px 14px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    color: "#6b7280",
    borderBottom: "2px solid transparent",
  },
  tabActive: {
    color: "#2563eb",
    borderBottom: "2px solid #2563eb",
  },
  tabDisabled: {
    color: "#d1d5db",
    cursor: "not-allowed",
  },
  soon: { fontSize: 10, fontWeight: 400, color: "#9ca3af", marginLeft: 3 },
  content: {
    padding: 24,
    maxWidth: 1200,
    margin: "0 auto",
  },
};
