import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAgentUsages, refreshAgentCard } from "../../api/client";
import { Drawer } from "../shared/Drawer";
import type { Agent } from "../../types";

interface Props {
  open: boolean;
  agent: Agent | null;
  onClose: () => void;
  onOpenGraph: (graphId: string) => void;
}

export function AgentDetailsDrawer({ open, agent, onClose, onOpenGraph }: Props) {
  const qc = useQueryClient();

  const { data: usages = [], isLoading: usagesLoading } = useQuery({
    queryKey: ["agent-usages", agent?.id],
    queryFn: () => getAgentUsages(agent!.id),
    enabled: open && Boolean(agent?.id),
    staleTime: 5_000,
  });

  const refreshMut = useMutation({
    mutationFn: () => refreshAgentCard(agent!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  if (!agent) return null;

  return (
    <Drawer open={open} title={agent.name} onClose={onClose}>
      <section style={styles.section}>
        <div style={styles.sectionLabel}>Summary</div>
        <Row label="ID" value={<code style={styles.code}>{agent.id}</code>} />
        <Row label="Type" value={agent.agent_type === "llm" ? "LLM" : "A2A (HTTP)"} />
        {agent.agent_type === "llm" && agent.model && (
          <Row label="Model" value={<code style={styles.code}>{agent.model}</code>} />
        )}
        {agent.agent_type === "http" && (
          <>
            <Row label="URL" value={<code style={styles.code}>{agent.url ?? "—"}</code>} />
            <Row label="Card URL" value={<code style={styles.code}>{agent.agent_card_url ?? "—"}</code>} />
          </>
        )}
        <Row label="Created" value={new Date(agent.created_at).toLocaleString()} />
        {agent.description && (
          <Row label="Description" value={agent.description} />
        )}
      </section>

      {agent.agent_type === "http" && (
        <section style={styles.section}>
          <div style={styles.sectionHeaderRow}>
            <div style={styles.sectionLabel}>Agent Card</div>
            <button
              style={styles.refreshBtn}
              onClick={() => refreshMut.mutate()}
              disabled={refreshMut.isPending}
            >
              {refreshMut.isPending ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
          {refreshMut.isError && (
            <div style={styles.errorBox}>
              Refresh failed. The agent may be unreachable or not serving /.well-known/agent.json.
            </div>
          )}
          {agent.agent_card_json ? (
            <pre style={styles.jsonBox}>
              {JSON.stringify(agent.agent_card_json, null, 2)}
            </pre>
          ) : (
            <div style={styles.emptyBox}>
              No agent card fetched yet. Click Refresh to try again.
            </div>
          )}
        </section>
      )}

      {agent.agent_type === "llm" && agent.system_prompt && (
        <section style={styles.section}>
          <div style={styles.sectionLabel}>System Prompt</div>
          <pre style={styles.textBox}>{agent.system_prompt}</pre>
        </section>
      )}

      <section style={styles.section}>
        <div style={styles.sectionLabel}>Used by</div>
        {usagesLoading ? (
          <div style={styles.helpText}>Checking…</div>
        ) : usages.length === 0 ? (
          <div style={styles.helpText}>Not referenced by any graph.</div>
        ) : (
          <ul style={styles.usagesList}>
            {usages.map((u, i) => (
              <li key={`${u.graph_id}-${u.node_key}-${i}`} style={styles.usageItem}>
                <button
                  style={styles.usageLink}
                  onClick={() => { onOpenGraph(u.graph_id); onClose(); }}
                >
                  {u.graph_name}
                </button>
                <span style={styles.usageNode}>  ·  node <code>{u.node_key}</code></span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Drawer>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={styles.row}>
      <div style={styles.rowLabel}>{label}</div>
      <div style={styles.rowValue}>{value}</div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  section: {
    marginBottom: 22,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 8,
  },
  sectionHeaderRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  row: {
    display: "flex",
    gap: 12,
    marginBottom: 6,
    fontSize: 13,
  },
  rowLabel: {
    flexShrink: 0,
    width: 90,
    color: "#6b7280",
    fontSize: 12,
  },
  rowValue: {
    color: "#111827",
    wordBreak: "break-all",
    flex: 1,
  },
  code: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
  },
  jsonBox: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 12,
    borderRadius: 6,
    fontSize: 11,
    fontFamily: "monospace",
    maxHeight: 320,
    overflow: "auto",
    margin: 0,
  },
  textBox: {
    background: "#f9fafb",
    border: "1px solid #e5e7eb",
    padding: 10,
    borderRadius: 5,
    fontSize: 12,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    margin: 0,
    fontFamily: "system-ui, sans-serif",
    maxHeight: 200,
    overflow: "auto",
  },
  emptyBox: {
    background: "#fffbeb",
    border: "1px solid #fde68a",
    color: "#92400e",
    padding: "10px 12px",
    borderRadius: 5,
    fontSize: 12,
  },
  errorBox: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
    marginBottom: 8,
  },
  refreshBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 10px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
  },
  helpText: {
    fontSize: 12,
    color: "#6b7280",
  },
  usagesList: {
    margin: 0,
    paddingLeft: 18,
    fontSize: 13,
  },
  usageItem: {
    marginBottom: 4,
  },
  usageLink: {
    background: "none",
    border: "none",
    padding: 0,
    cursor: "pointer",
    color: "#2563eb",
    fontWeight: 600,
    textDecoration: "underline",
    fontSize: 13,
  },
  usageNode: {
    color: "#6b7280",
    fontSize: 11,
  },
};
