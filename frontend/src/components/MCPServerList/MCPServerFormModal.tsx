import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createMCPServer, updateMCPServer } from "../../api/client";
import { Modal } from "../shared/Modal";
import type { MCPServer, MCPServerCreate, MCPServerUpdate } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  server?: MCPServer | null;
  onResult?: (result: { server: MCPServer; mode: "create" | "update"; toolsDiscovered: number | null }) => void;
}

type TransportOpt = "http" | "stdio";

interface EnvVarRow {
  key: string;
  value: string;
}

interface FormState {
  name: string;
  description: string;
  transport: TransportOpt;
  url: string;
  command: string;
  args: string; // space-separated for simple editing
  env_vars: EnvVarRow[];
}

const EMPTY: FormState = {
  name: "",
  description: "",
  transport: "http",
  url: "",
  command: "",
  args: "",
  env_vars: [],
};

export function MCPServerFormModal({ open, onClose, server, onResult }: Props) {
  const qc = useQueryClient();
  const isEdit = Boolean(server);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (server) {
      setForm({
        name: server.name ?? "",
        description: server.description ?? "",
        transport: (server.transport === "stdio" ? "stdio" : "http"),
        url: server.url ?? "",
        command: server.command ?? "",
        args: (server.args ?? []).join(" "),
        env_vars: Object.entries(server.env_vars ?? {}).map(([key, value]) => ({ key, value })),
      });
    } else {
      setForm(EMPTY);
    }
    setError(null);
  }, [open, server]);

  const createMut = useMutation({
    mutationFn: (body: MCPServerCreate) => createMCPServer(body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      onResult?.({
        server: created,
        mode: "create",
        toolsDiscovered: created.tools_json?.length ?? null,
      });
      onClose();
    },
    onError: (err: unknown) => setError(extractError(err)),
  });

  const updateMut = useMutation({
    mutationFn: (body: MCPServerUpdate) => updateMCPServer(server!.id, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      onResult?.({
        server: updated,
        mode: "update",
        toolsDiscovered: updated.tools_json?.length ?? null,
      });
      onClose();
    },
    onError: (err: unknown) => setError(extractError(err)),
  });

  const pending = createMut.isPending || updateMut.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!form.name.trim()) {
      setError("Name is required");
      return;
    }

    // Build env_vars dict, dropping empty rows
    const envDict: Record<string, string> = {};
    for (const row of form.env_vars) {
      const k = row.key.trim();
      if (k) envDict[k] = row.value;
    }

    if (isEdit) {
      const body: MCPServerUpdate = {
        name: form.name.trim(),
        description: form.description.trim() || null,
      };
      if (form.transport === "http") {
        if (!form.url.trim()) { setError("URL is required for HTTP transport"); return; }
        body.url = form.url.trim();
      } else {
        if (!form.command.trim()) { setError("Command is required for stdio transport"); return; }
        body.command = form.command.trim();
        body.args = form.args.trim() ? form.args.trim().split(/\s+/) : [];
        body.env_vars = Object.keys(envDict).length ? envDict : null;
      }
      updateMut.mutate(body);
    } else {
      const body: MCPServerCreate = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        transport: form.transport,
      };
      if (form.transport === "http") {
        if (!form.url.trim()) { setError("URL is required for HTTP transport"); return; }
        body.url = form.url.trim();
      } else {
        if (!form.command.trim()) { setError("Command is required for stdio transport"); return; }
        body.command = form.command.trim();
        body.args = form.args.trim() ? form.args.trim().split(/\s+/) : [];
        body.env_vars = Object.keys(envDict).length ? envDict : null;
      }
      createMut.mutate(body);
    }
  };

  const addEnvRow = () => setForm({ ...form, env_vars: [...form.env_vars, { key: "", value: "" }] });
  const removeEnvRow = (i: number) =>
    setForm({ ...form, env_vars: form.env_vars.filter((_, j) => j !== i) });
  const setEnvRow = (i: number, patch: Partial<EnvVarRow>) =>
    setForm({
      ...form,
      env_vars: form.env_vars.map((row, j) => (j === i ? { ...row, ...patch } : row)),
    });

  return (
    <Modal
      open={open}
      title={isEdit ? "Edit MCP Server" : "New MCP Server"}
      onClose={onClose}
      locked={pending}
      maxWidth={560}
    >
      <form onSubmit={submit}>
        <Field label="Name">
          <input
            style={styles.input}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            disabled={pending}
            autoFocus
          />
        </Field>

        <Field label="Description">
          <textarea
            style={{ ...styles.input, height: 56, resize: "vertical" }}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            disabled={pending}
          />
        </Field>

        <Field label="Transport">
          <select
            style={styles.select}
            value={form.transport}
            onChange={(e) => setForm({ ...form, transport: e.target.value as TransportOpt })}
            disabled={pending || isEdit}
          >
            <option value="http">HTTP (SSE)</option>
            <option value="stdio">stdio (subprocess)</option>
          </select>
          {isEdit && (
            <div style={styles.helpText}>Transport cannot be changed after creation.</div>
          )}
        </Field>

        {form.transport === "http" && (
          <Field label="URL">
            <input
              style={styles.input}
              placeholder="http://my-mcp-server.example.com/sse"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              disabled={pending}
            />
            {isEdit && (
              <div style={styles.helpText}>
                Click Refresh after saving to re-discover tools.
              </div>
            )}
          </Field>
        )}

        {form.transport === "stdio" && (
          <>
            <div style={styles.stdioWarn}>
              <strong>⚠ stdio servers require the command script to already exist on the backend container's filesystem.</strong>
              {" "}Scripts cannot be uploaded through this UI. Use <strong>HTTP</strong> transport for bring-your-own servers.
              If the command isn't present, registration will still succeed but tool discovery will fail —
              click Refresh to retry once the script is in place.
            </div>
            <Field label="Command">
              <input
                style={styles.input}
                placeholder="/usr/local/bin/python3"
                value={form.command}
                onChange={(e) => setForm({ ...form, command: e.target.value })}
                disabled={pending}
              />
            </Field>
            <Field label="Args (space-separated)">
              <input
                style={styles.input}
                placeholder="/app/seed_services/mock_mcp_server.py"
                value={form.args}
                onChange={(e) => setForm({ ...form, args: e.target.value })}
                disabled={pending}
              />
              <div style={styles.helpText}>
                Each space-separated token becomes an argument. Use quoted paths if they contain spaces — one per arg.
              </div>
            </Field>
            <Field label="Environment variables">
              <div>
                {form.env_vars.map((row, i) => (
                  <div key={i} style={styles.envRow}>
                    <input
                      style={{ ...styles.input, flex: 1 }}
                      placeholder="KEY"
                      value={row.key}
                      onChange={(e) => setEnvRow(i, { key: e.target.value })}
                      disabled={pending}
                    />
                    <input
                      style={{ ...styles.input, flex: 2 }}
                      placeholder="value"
                      value={row.value}
                      onChange={(e) => setEnvRow(i, { value: e.target.value })}
                      disabled={pending}
                    />
                    <button
                      type="button"
                      style={styles.removeBtn}
                      onClick={() => removeEnvRow(i)}
                      disabled={pending}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  style={styles.addBtn}
                  onClick={addEnvRow}
                  disabled={pending}
                >
                  + Add env var
                </button>
              </div>
            </Field>
          </>
        )}

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.actions}>
          <button
            type="button"
            style={styles.cancelBtn}
            onClick={onClose}
            disabled={pending}
          >
            Cancel
          </button>
          <button
            type="submit"
            style={styles.submitBtn}
            disabled={pending}
          >
            {pending ? "Saving…" : isEdit ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={styles.label}>{label}</label>
      {children}
    </div>
  );
}

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { error?: string; detail?: string } } }).response;
    return resp?.data?.error ?? resp?.data?.detail ?? "Request failed";
  }
  return String(err);
}

const styles: Record<string, React.CSSProperties> = {
  label: {
    display: "block", fontSize: 11, fontWeight: 600, color: "#374151", marginBottom: 4,
  },
  input: {
    width: "100%", border: "1px solid #d1d5db", borderRadius: 5,
    padding: "7px 10px", fontSize: 13, boxSizing: "border-box",
    fontFamily: "system-ui, sans-serif",
  },
  select: {
    width: "100%", border: "1px solid #d1d5db", borderRadius: 5,
    padding: "7px 10px", fontSize: 13, boxSizing: "border-box",
    background: "#fff", cursor: "pointer",
  },
  helpText: { fontSize: 11, color: "#6b7280", marginTop: 3 },
  stdioWarn: {
    background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 5,
    padding: "10px 12px", fontSize: 12, color: "#78350f",
    marginBottom: 12, lineHeight: 1.5,
  },
  envRow: { display: "flex", gap: 6, marginBottom: 4 },
  removeBtn: {
    background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 5,
    padding: "0 10px", cursor: "pointer", color: "#dc2626", fontWeight: 700,
  },
  addBtn: {
    background: "#f3f4f6", border: "1px dashed #d1d5db", borderRadius: 5,
    padding: "6px 12px", cursor: "pointer", fontSize: 12, marginTop: 4,
  },
  error: {
    background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 5,
    padding: "8px 12px", fontSize: 12, color: "#dc2626", marginBottom: 12,
  },
  actions: {
    display: "flex", gap: 8, justifyContent: "flex-end",
    marginTop: 8, borderTop: "1px solid #e5e7eb", paddingTop: 14,
  },
  cancelBtn: {
    background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: 6,
    padding: "8px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600,
  },
  submitBtn: {
    background: "#2563eb", color: "#fff", border: "none", borderRadius: 6,
    padding: "8px 20px", cursor: "pointer", fontSize: 13, fontWeight: 700,
  },
};
