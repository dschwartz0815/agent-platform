import { useQuery } from "@tanstack/react-query";
import type { Node } from "@xyflow/react";
import { useMemo } from "react";
import { listAgents, listMCPServers } from "../../../api/client";
import type { Agent, MCPServer, MCPTool } from "../../../types";

const ANTHROPIC_MODELS = [
  { id: "claude-opus-4-6",          label: "Claude Opus 4.6 (most capable)" },
  { id: "claude-sonnet-4-6",        label: "Claude Sonnet 4.6 (balanced)" },
  { id: "claude-haiku-4-5-20251001",label: "Claude Haiku 4.5 (fast)" },
  { id: "claude-3-5-sonnet-20241022",label: "claude-3-5-sonnet (legacy)" },
];

interface Props {
  node: Node | null;
  onUpdate: (id: string, changes: { label?: string; config_json?: Record<string, unknown> }) => void;
}

export function PropertiesPanel({ node, onUpdate }: Props) {
  const { data: mcpServers = [] } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: listMCPServers,
    staleTime: 30_000,
  });
  const { data: agents = [] } = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
    staleTime: 30_000,
  });

  if (!node) {
    return (
      <div style={{ padding: 12, color: "#9ca3af", fontSize: 13 }}>
        Click a node to edit its properties.
      </div>
    );
  }

  const data = node.data as {
    label: string;
    node_type: string;
    config_json: Record<string, unknown>;
  };

  const set = (key: string, value: unknown) =>
    onUpdate(node.id, { config_json: { ...data.config_json, [key]: value } });

  const selectedServerId = String(data.config_json.mcp_server_id ?? "");
  const selectedServer = mcpServers.find((s) => s.id === selectedServerId);
  const availableTools: MCPTool[] = selectedServer?.tools_json ?? [];

  return (
    <div style={{ padding: 12 }}>
      <div style={styles.sectionHeader}>Properties</div>

      <Field label="Label">
        <input
          style={styles.input}
          value={data.label}
          onChange={(e) => onUpdate(node.id, { label: e.target.value })}
        />
      </Field>

      {/* ------------------------------------------------------------------ */}
      {/* LLM node                                                             */}
      {/* ------------------------------------------------------------------ */}
      {data.node_type === "llm" && (
        <>
          <Field label="Model">
            <select
              style={styles.select}
              value={String(data.config_json.model ?? "claude-sonnet-4-6")}
              onChange={(e) => set("model", e.target.value)}
            >
              {ANTHROPIC_MODELS.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </Field>
          <Field label="System Prompt">
            <textarea
              style={{ ...styles.input, height: 100, resize: "vertical" }}
              value={String(data.config_json.system_prompt ?? "")}
              onChange={(e) => set("system_prompt", e.target.value)}
            />
          </Field>
          <Field label="Context key">
            <input
              style={styles.input}
              value={String(data.config_json.context_key ?? "")}
              onChange={(e) => set("context_key", e.target.value)}
            />
          </Field>
          <Field label="Include context snapshot">
            <input
              type="checkbox"
              checked={Boolean(data.config_json.include_context)}
              onChange={(e) => set("include_context", e.target.checked)}
            />
            <span style={{ fontSize: 11, color: "#6b7280", marginLeft: 6 }}>
              Pass full state context to model (use for consolidator nodes)
            </span>
          </Field>
        </>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Router node                                                          */}
      {/* ------------------------------------------------------------------ */}
      {data.node_type === "router" && (
        <>
          <Field label="Source field (dot-path)">
            <input
              style={styles.input}
              placeholder="context.classification.risk_level"
              value={String(data.config_json.source ?? "")}
              onChange={(e) => set("source", e.target.value)}
            />
          </Field>
          <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2, marginBottom: 8 }}>
            Routes map from the resolved value to a destination node key.
            Edit them via the graph's edges (set a condition on each outgoing edge).
          </div>
          <Field label="Default destination">
            <input
              style={styles.input}
              placeholder="summarize"
              value={String(data.config_json.default ?? "")}
              onChange={(e) => set("default", e.target.value)}
            />
          </Field>
        </>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* MCP Tool node                                                        */}
      {/* ------------------------------------------------------------------ */}
      {data.node_type === "mcp_tool" && (
        <McpToolFields
          config={data.config_json}
          mcpServers={mcpServers}
          selectedServer={selectedServer}
          availableTools={availableTools}
          set={set}
          onUpdate={(c) => onUpdate(node.id, { config_json: c })}
        />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* ReAct agent node                                                     */}
      {/* ------------------------------------------------------------------ */}
      {data.node_type === "agent" && (
        <>
          <Field label="Model">
            <select
              style={styles.select}
              value={String(data.config_json.model ?? "claude-sonnet-4-6")}
              onChange={(e) => set("model", e.target.value)}
            >
              {ANTHROPIC_MODELS.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </Field>
          <Field label="System Prompt">
            <textarea
              style={{ ...styles.input, height: 80, resize: "vertical" }}
              value={String(data.config_json.system_prompt ?? "")}
              onChange={(e) => set("system_prompt", e.target.value)}
            />
          </Field>
          <Field label="MCP Servers">
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>
              Select servers whose tools this agent can call.
            </div>
            {mcpServers.map((srv) => {
              const ids: string[] = Array.isArray(data.config_json.mcp_server_ids)
                ? (data.config_json.mcp_server_ids as string[])
                : [];
              const checked = ids.includes(srv.id);
              return (
                <label key={srv.id} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...ids, srv.id]
                        : ids.filter((id) => id !== srv.id);
                      set("mcp_server_ids", next);
                    }}
                  />
                  {srv.name}
                </label>
              );
            })}
          </Field>
        </>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* A2A agent node                                                       */}
      {/* ------------------------------------------------------------------ */}
      {data.node_type === "a2a" && (
        <>
          <Field label="A2A Agent">
            <select
              style={styles.select}
              value={String(data.config_json.agent_id ?? "")}
              onChange={(e) => set("agent_id", e.target.value)}
            >
              <option value="">— select agent —</option>
              {agents
                .filter((a) => a.agent_type === "http")
                .map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
            </select>
          </Field>
          {data.config_json.agent_id && (() => {
            const ag = agents.find((a) => a.id === data.config_json.agent_id);
            return ag ? (
              <div style={styles.pill}>
                <span style={{ fontWeight: 600 }}>URL:</span> {ag.url}
                {ag.agent_card_json && (
                  <span style={{ marginLeft: 6, color: "#059669" }}>✓ card fetched</span>
                )}
              </div>
            ) : null;
          })()}
          <Field label="Context key">
            <input
              style={styles.input}
              value={String(data.config_json.context_key ?? "")}
              onChange={(e) => set("context_key", e.target.value)}
            />
          </Field>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Tool sub-form
// ---------------------------------------------------------------------------

interface McpToolFieldsProps {
  config: Record<string, unknown>;
  mcpServers: MCPServer[];
  selectedServer: MCPServer | undefined;
  availableTools: MCPTool[];
  set: (key: string, value: unknown) => void;
  onUpdate: (config: Record<string, unknown>) => void;
}

function McpToolFields({
  config, mcpServers, selectedServer, availableTools, set, onUpdate,
}: McpToolFieldsProps) {
  const selectedTool = availableTools.find((t) => t.name === config.tool_name);

  const defaultArgs = useMemo(() => {
    if (!selectedTool?.input_schema) return "{}";
    const props = (selectedTool.input_schema as { properties?: Record<string, unknown> }).properties ?? {};
    const empty: Record<string, string> = {};
    for (const k of Object.keys(props)) empty[k] = "";
    return JSON.stringify(empty, null, 2);
  }, [selectedTool]);

  const argsStr = useMemo(() => {
    const raw = config.arguments;
    if (!raw) return defaultArgs;
    try { return JSON.stringify(raw, null, 2); } catch { return "{}"; }
  }, [config.arguments, defaultArgs]);

  return (
    <>
      <Field label="MCP Server">
        <select
          style={styles.select}
          value={String(config.mcp_server_id ?? "")}
          onChange={(e) => {
            // Reset tool when server changes
            onUpdate({ ...config, mcp_server_id: e.target.value, tool_name: "", arguments: {} });
          }}
        >
          <option value="">— select server —</option>
          {mcpServers.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </Field>

      {selectedServer && (
        <div style={styles.pill}>
          <span style={{ fontWeight: 600 }}>Transport:</span> {selectedServer.transport}
          {selectedServer.tools_json && (
            <span style={{ marginLeft: 6, color: "#059669" }}>
              · {selectedServer.tools_json.length} tools discovered
            </span>
          )}
        </div>
      )}

      <Field label="Tool">
        <select
          style={styles.select}
          value={String(config.tool_name ?? "")}
          onChange={(e) => {
            const tool = availableTools.find((t) => t.name === e.target.value);
            const props = (tool?.input_schema as { properties?: Record<string, unknown> } | undefined)?.properties ?? {};
            const emptyArgs: Record<string, string> = {};
            for (const k of Object.keys(props)) emptyArgs[k] = "";
            onUpdate({ ...config, tool_name: e.target.value, arguments: emptyArgs });
          }}
          disabled={availableTools.length === 0}
        >
          <option value="">
            {availableTools.length === 0 ? "— select server first —" : "— select tool —"}
          </option>
          {availableTools.map((t) => (
            <option key={t.name} value={t.name}>{t.name}</option>
          ))}
        </select>
        {selectedTool?.description && (
          <div style={{ fontSize: 11, color: "#6b7280", marginTop: 3 }}>{selectedTool.description}</div>
        )}
      </Field>

      <Field label="Arguments (JSON, supports {{path}} templates)">
        <textarea
          style={{ ...styles.input, height: 80, resize: "vertical", fontFamily: "monospace", fontSize: 11 }}
          value={argsStr}
          onChange={(e) => {
            try {
              set("arguments", JSON.parse(e.target.value));
            } catch {
              // don't update on invalid JSON — let user keep typing
            }
          }}
        />
      </Field>

      <Field label="Output key">
        <input
          style={styles.input}
          value={String(config.output_key ?? "")}
          onChange={(e) => set("output_key", e.target.value)}
        />
      </Field>
    </>
  );
}

// ---------------------------------------------------------------------------
// Field wrapper
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: "#374151", display: "block", marginBottom: 3 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  sectionHeader: {
    fontWeight: 700,
    fontSize: 11,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "5px 8px",
    fontSize: 12,
    boxSizing: "border-box",
    fontFamily: "system-ui, sans-serif",
  },
  select: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "5px 8px",
    fontSize: 12,
    boxSizing: "border-box",
    background: "#fff",
    cursor: "pointer",
  },
  pill: {
    background: "#f3f4f6",
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    padding: "4px 8px",
    fontSize: 11,
    color: "#374151",
    marginBottom: 8,
  },
};
