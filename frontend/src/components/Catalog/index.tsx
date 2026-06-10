import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  installCatalogAgent,
  installCatalogMCPServer,
  listCatalog,
} from "../../api/client";
import type { CatalogEntry, Workspace } from "../../types";

interface Props {
  workspace: Workspace;
}

type Filter = "all" | "agent" | "mcp_server";

interface Banner {
  kind: "success" | "error";
  text: string;
}

/**
 * Cross-workspace catalog. Entries published by any workspace can be browsed
 * here and installed into the active workspace (a copy with lineage).
 */
export function Catalog({ workspace }: Props) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [banner, setBanner] = useState<Banner | null>(null);

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["catalog"],
    queryFn: () => listCatalog(),
  });

  const canInstall = workspace.role !== "viewer";

  const installMut = useMutation({
    mutationFn: async (entry: CatalogEntry): Promise<void> => {
      if (entry.entry_type === "agent") await installCatalogAgent(entry.id);
      else await installCatalogMCPServer(entry.id);
    },
    onSuccess: (_data, entry) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      setBanner({
        kind: "success",
        text: `Installed "${entry.name}" into ${workspace.name}. Find it under ${
          entry.entry_type === "agent" ? "Agents" : "Tools"
        }.`,
      });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      setBanner({ kind: "error", text: detail || "Install failed." });
    },
  });

  const visible = entries.filter((e) => filter === "all" || e.entry_type === filter);

  if (isLoading) return <div style={styles.container}>Loading catalog…</div>;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={{ margin: 0 }}>Catalog</h2>
        <div style={styles.filters}>
          {(["all", "agent", "mcp_server"] as Filter[]).map((f) => (
            <button
              key={f}
              style={{ ...styles.filterBtn, ...(filter === f ? styles.filterActive : {}) }}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "All" : f === "agent" ? "Agents" : "MCP Servers"}
            </button>
          ))}
        </div>
      </div>

      <p style={styles.intro}>
        Agents and MCP servers published by any workspace. Installing copies an entry
        into <b>{workspace.name}</b> so your graphs can use it.
      </p>

      {banner && (
        <div style={{ ...styles.banner, ...(banner.kind === "success" ? styles.bannerOk : styles.bannerErr) }}>
          <span>{banner.text}</span>
          <button style={styles.bannerClose} onClick={() => setBanner(null)}>×</button>
        </div>
      )}

      {visible.length === 0 && (
        <p style={{ color: "#6b7280" }}>
          Nothing published yet. Workspace admins can publish agents and MCP servers
          from their registry pages.
        </p>
      )}

      <div style={styles.grid}>
        {visible.map((e) => (
          <div key={`${e.entry_type}-${e.id}`} style={styles.card}>
            <div style={styles.cardTitleRow}>
              <span style={styles.cardTitle}>{e.name}</span>
              <span style={e.entry_type === "agent" ? styles.badgeAgent : styles.badgeMcp}>
                {e.entry_type === "agent" ? "Agent" : "MCP Server"}
              </span>
            </div>
            {e.description && <div style={styles.cardDesc}>{e.description}</div>}
            <div style={styles.cardMeta}>
              <span style={styles.wsBadge}>{e.workspace_name}</span>
              {e.agent_type && <code style={styles.codeMeta}>{e.agent_type}</code>}
              {e.model && <code style={styles.codeMeta}>{e.model}</code>}
              {e.transport && <code style={styles.codeMeta}>{e.transport}</code>}
              {e.tool_count != null && e.tool_count > 0 && (
                <span style={styles.metaText}>{e.tool_count} tools</span>
              )}
              {(e.tags ?? []).map((t) => (
                <span key={t} style={styles.tag}>{t}</span>
              ))}
            </div>
            <div style={styles.cardActions}>
              {e.owned_by_caller_workspace ? (
                <span style={styles.ownedNote}>Published by this workspace</span>
              ) : (
                <button
                  style={{ ...styles.installBtn, ...(canInstall ? {} : styles.btnDisabled) }}
                  disabled={!canInstall || installMut.isPending}
                  title={canInstall ? undefined : "Requires the editor role"}
                  onClick={() => installMut.mutate(e)}
                >
                  {installMut.isPending ? "Installing…" : "Install"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 1100, margin: "0 auto", padding: 24 },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  intro: { color: "#6b7280", fontSize: 14, marginTop: 0 },
  filters: { display: "flex", gap: 6 },
  filterBtn: {
    background: "#fff", border: "1px solid #d1d5db", borderRadius: 6,
    padding: "6px 12px", fontSize: 13, cursor: "pointer", fontFamily: "inherit",
  },
  filterActive: { background: "#1e293b", color: "#fff", borderColor: "#1e293b" },
  banner: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    borderRadius: 8, padding: "10px 14px", fontSize: 14, marginBottom: 16,
  },
  bannerOk: { background: "#ecfdf5", border: "1px solid #6ee7b7", color: "#065f46" },
  bannerErr: { background: "#fef2f2", border: "1px solid #fca5a5", color: "#991b1b" },
  bannerClose: { background: "none", border: "none", cursor: "pointer", fontSize: 16 },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 },
  card: {
    background: "#fff", border: "1px solid #e5e7eb", borderRadius: 10,
    padding: 16, display: "flex", flexDirection: "column", gap: 8,
  },
  cardTitleRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  cardTitle: { fontWeight: 700, fontSize: 15 },
  cardDesc: { color: "#4b5563", fontSize: 13, lineHeight: 1.5 },
  cardMeta: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  cardActions: { marginTop: "auto", paddingTop: 8 },
  badgeAgent: {
    background: "#eef2ff", color: "#4338ca", borderRadius: 999,
    padding: "2px 10px", fontSize: 11, fontWeight: 700,
  },
  badgeMcp: {
    background: "#f0fdf4", color: "#15803d", borderRadius: 999,
    padding: "2px 10px", fontSize: 11, fontWeight: 700,
  },
  wsBadge: {
    background: "#f3f4f6", color: "#374151", borderRadius: 999,
    padding: "2px 10px", fontSize: 11, fontWeight: 600,
  },
  tag: {
    background: "#fefce8", color: "#854d0e", borderRadius: 999,
    padding: "2px 8px", fontSize: 11,
  },
  codeMeta: {
    background: "#f3f4f6", borderRadius: 4, padding: "1px 6px",
    fontSize: 12, color: "#374151",
  },
  metaText: { fontSize: 12, color: "#6b7280" },
  installBtn: {
    background: "#1e293b", color: "#fff", border: "none", borderRadius: 6,
    padding: "6px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    fontFamily: "inherit",
  },
  btnDisabled: { opacity: 0.5, cursor: "not-allowed" },
  ownedNote: { fontSize: 12, color: "#6b7280", fontStyle: "italic" },
};
