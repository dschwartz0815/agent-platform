import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createAgent, updateAgent } from "../../api/client";
import { Modal } from "../shared/Modal";
import { ANTHROPIC_MODELS, DEFAULT_MODEL_ID } from "../../constants/models";
import type { Agent, AgentCreate, AgentUpdate } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** If set, the modal opens in edit mode pre-filled with this agent's values. */
  agent?: Agent | null;
  onResult?: (result: { agent: Agent; mode: "create" | "update"; cardFetched: boolean }) => void;
}

type AgentTypeOpt = "llm" | "http";

interface FormState {
  name: string;
  description: string;
  agent_type: AgentTypeOpt;
  model: string;
  system_prompt: string;
  url: string;
  agent_card_url: string;
}

const EMPTY: FormState = {
  name: "",
  description: "",
  agent_type: "http",
  model: DEFAULT_MODEL_ID,
  system_prompt: "",
  url: "",
  agent_card_url: "",
};

export function AgentFormModal({ open, onClose, agent, onResult }: Props) {
  const qc = useQueryClient();
  const isEdit = Boolean(agent);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (agent) {
      setForm({
        name: agent.name ?? "",
        description: agent.description ?? "",
        agent_type: (agent.agent_type === "llm" ? "llm" : "http"),
        model: agent.model ?? DEFAULT_MODEL_ID,
        system_prompt: agent.system_prompt ?? "",
        url: agent.url ?? "",
        agent_card_url: agent.agent_card_url ?? "",
      });
    } else {
      setForm(EMPTY);
    }
    setError(null);
  }, [open, agent]);

  const createMut = useMutation({
    mutationFn: (body: AgentCreate) => createAgent(body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      onResult?.({ agent: created, mode: "create", cardFetched: Boolean(created.agent_card_json) });
      onClose();
    },
    onError: (err: unknown) => setError(extractError(err)),
  });

  const updateMut = useMutation({
    mutationFn: (body: AgentUpdate) => updateAgent(agent!.id, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      onResult?.({ agent: updated, mode: "update", cardFetched: Boolean(updated.agent_card_json) });
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

    if (isEdit) {
      // In edit mode, agent_type is immutable (backend AgentUpdate doesn't accept it)
      const body: AgentUpdate = {
        name: form.name.trim(),
        description: form.description.trim() || null,
      };
      if (form.agent_type === "llm") {
        body.model = form.model;
        body.system_prompt = form.system_prompt.trim() || null;
      } else {
        if (!form.url.trim()) {
          setError("URL is required for A2A (HTTP) agents");
          return;
        }
        body.url = form.url.trim();
        body.agent_card_url = form.agent_card_url.trim() || null;
      }
      updateMut.mutate(body);
    } else {
      const body: AgentCreate = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        agent_type: form.agent_type,
      };
      if (form.agent_type === "llm") {
        body.model = form.model;
        body.system_prompt = form.system_prompt.trim() || null;
      } else {
        if (!form.url.trim()) {
          setError("URL is required for A2A (HTTP) agents");
          return;
        }
        body.url = form.url.trim();
        body.agent_card_url = form.agent_card_url.trim() || null;
      }
      createMut.mutate(body);
    }
  };

  return (
    <Modal
      open={open}
      title={isEdit ? "Edit Agent" : "New Agent"}
      onClose={onClose}
      locked={pending}
      maxWidth={520}
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
            style={{ ...styles.input, height: 60, resize: "vertical" }}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            disabled={pending}
          />
        </Field>

        <Field label="Type">
          <select
            style={styles.select}
            value={form.agent_type}
            onChange={(e) => setForm({ ...form, agent_type: e.target.value as AgentTypeOpt })}
            disabled={pending || isEdit}
          >
            <option value="llm">LLM (direct Claude call)</option>
            <option value="http">A2A Agent (HTTP)</option>
          </select>
          {isEdit && (
            <div style={styles.helpText}>
              Type cannot be changed after creation.
            </div>
          )}
        </Field>

        {form.agent_type === "llm" && (
          <>
            <Field label="Model">
              <select
                style={styles.select}
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
                disabled={pending}
              >
                {ANTHROPIC_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </Field>
            <Field label="System Prompt">
              <textarea
                style={{ ...styles.input, height: 100, resize: "vertical" }}
                value={form.system_prompt}
                onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                disabled={pending}
              />
            </Field>
          </>
        )}

        {form.agent_type === "http" && (
          <>
            <Field label="URL">
              <input
                style={styles.input}
                placeholder="http://seed-agent:8001"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                disabled={pending}
              />
              {isEdit && (
                <div style={styles.helpText}>
                  Click Refresh after saving to re-discover the agent card.
                </div>
              )}
            </Field>
            <Field label="Agent Card URL (optional)">
              <input
                style={styles.input}
                placeholder="Leave blank for /.well-known/agent.json"
                value={form.agent_card_url}
                onChange={(e) => setForm({ ...form, agent_card_url: e.target.value })}
                disabled={pending}
              />
            </Field>
            <div style={styles.infoCallout}>
              ℹ On save, we'll try to fetch the agent card. If the endpoint isn't
              reachable, the agent will still be created — click Refresh to retry later.
            </div>
          </>
        )}

        {error && (
          <div style={styles.error}>{error}</div>
        )}

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
    display: "block",
    fontSize: 11,
    fontWeight: 600,
    color: "#374151",
    marginBottom: 4,
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
    fontFamily: "system-ui, sans-serif",
  },
  select: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
    background: "#fff",
    cursor: "pointer",
  },
  helpText: {
    fontSize: 11,
    color: "#6b7280",
    marginTop: 3,
  },
  infoCallout: {
    background: "#eff6ff",
    border: "1px solid #bfdbfe",
    borderRadius: 5,
    padding: "8px 12px",
    fontSize: 12,
    color: "#1e40af",
    marginBottom: 12,
    marginTop: 4,
  },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    borderRadius: 5,
    padding: "8px 12px",
    fontSize: 12,
    color: "#dc2626",
    marginBottom: 12,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    marginTop: 8,
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  submitBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
  },
};
