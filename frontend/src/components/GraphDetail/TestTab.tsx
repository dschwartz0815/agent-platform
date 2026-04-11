import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createExample, deleteExample, streamRun } from "../../api/client";
import { SchemaFormGenerator } from "../shared/SchemaFormGenerator";
import type { Graph, TestExample } from "../../types";

interface Props {
  graph: Graph;
}

interface LiveEvent {
  event: string;
  node: string | null;
  data: unknown;
  ts: number;
}

export function TestTab({ graph }: Props) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"form" | "json">("form");
  const [input, setInput] = useState<Record<string, unknown>>({});
  const [jsonText, setJsonText] = useState<string>(() => JSON.stringify({}, null, 2));
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [exampleName, setExampleName] = useState("");

  const examples: TestExample[] = (graph.test_examples as TestExample[] | null) ?? [];

  const createExampleMut = useMutation({
    mutationFn: (ex: { name: string; input: Record<string, unknown>; output: Record<string, unknown> | null }) =>
      createExample(graph.id, ex),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graph.id] });
      setSaveOpen(false);
      setExampleName("");
    },
  });

  const deleteExampleMut = useMutation({
    mutationFn: (exampleId: string) => deleteExample(graph.id, exampleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["graph", graph.id] }),
  });

  const loadExample = (ex: TestExample) => {
    setInput(ex.input);
    setJsonText(JSON.stringify(ex.input, null, 2));
    setRunResult(null);
    setEvents([]);
    setError(null);
  };

  const runTest = () => {
    const payload = mode === "form" ? input : _safeParseJson(jsonText, setError);
    if (payload === null) return;
    setRunning(true);
    setEvents([]);
    setRunResult(null);
    setError(null);

    streamRun(
      graph.id,
      payload,
      (evt) => {
        setEvents((prev) => [...prev, { ...evt, ts: Date.now() }]);
        if (evt.event === "node_end") {
          // Accumulate latest output snapshot
          const data = evt.data as Record<string, unknown> | null;
          if (data) setRunResult((prev) => ({ ...(prev ?? {}), ...data }));
        }
      },
      () => setRunning(false),
      (err) => {
        setError(err);
        setRunning(false);
      }
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {examples.length > 0 && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Saved examples</div>
          <div style={styles.chipRow}>
            {examples.map((ex) => (
              <div key={ex.id} style={styles.chip}>
                <button style={styles.chipBtn} onClick={() => loadExample(ex)}>
                  ↺ {ex.name}
                </button>
                <button
                  style={styles.chipDel}
                  onClick={() => deleteExampleMut.mutate(ex.id)}
                  title="Delete example"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section style={styles.card}>
        <div style={styles.cardHeader}>
          <div style={styles.sectionLabel}>Input</div>
          <div style={styles.modeToggle}>
            <button
              style={{ ...styles.modeBtn, ...(mode === "form" ? styles.modeBtnActive : {}) }}
              onClick={() => setMode("form")}
            >
              Form
            </button>
            <button
              style={{ ...styles.modeBtn, ...(mode === "json" ? styles.modeBtnActive : {}) }}
              onClick={() => {
                setJsonText(JSON.stringify(input, null, 2));
                setMode("json");
              }}
            >
              JSON
            </button>
          </div>
        </div>

        {mode === "form" ? (
          <SchemaFormGenerator
            schema={graph.input_schema}
            value={input}
            onChange={setInput}
            disabled={running}
          />
        ) : (
          <textarea
            style={styles.jsonArea}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            disabled={running}
          />
        )}

        <div style={styles.actions}>
          <button style={styles.runBtn} onClick={runTest} disabled={running}>
            {running ? "Running…" : "▶ Run"}
          </button>
          {runResult && !running && (
            <button style={styles.saveBtn} onClick={() => setSaveOpen(true)}>
              + Save as example
            </button>
          )}
        </div>
      </section>

      {error && (
        <div style={styles.error}>{error}</div>
      )}

      {(events.length > 0 || runResult) && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Live events</div>
          <div style={styles.eventList}>
            {events.map((e, i) => (
              <div key={i} style={styles.eventRow}>
                <span style={styles.eventType}>{e.event}</span>
                {e.node && <span style={styles.eventNode}>{e.node}</span>}
              </div>
            ))}
          </div>

          {runResult && (
            <>
              <div style={{ ...styles.sectionLabel, marginTop: 12 }}>Result</div>
              <pre style={styles.resultBox}>{JSON.stringify(runResult, null, 2)}</pre>
            </>
          )}
        </section>
      )}

      {saveOpen && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Save as example</div>
          <input
            style={styles.input}
            placeholder="Example name"
            value={exampleName}
            onChange={(e) => setExampleName(e.target.value)}
          />
          <div style={styles.actions}>
            <button style={styles.cancelBtn} onClick={() => setSaveOpen(false)}>Cancel</button>
            <button
              style={styles.runBtn}
              disabled={!exampleName.trim() || createExampleMut.isPending}
              onClick={() =>
                createExampleMut.mutate({
                  name: exampleName.trim(),
                  input,
                  output: runResult,
                })
              }
            >
              Save
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function _safeParseJson(text: string, setError: (e: string) => void): Record<string, unknown> | null {
  try {
    return JSON.parse(text);
  } catch (e) {
    setError((e as Error).message);
    return null;
  }
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  chipRow: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap",
  },
  chip: {
    display: "flex",
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 16,
    overflow: "hidden",
  },
  chipBtn: {
    background: "none",
    border: "none",
    padding: "4px 12px",
    fontSize: 12,
    cursor: "pointer",
    color: "#374151",
  },
  chipDel: {
    background: "none",
    border: "none",
    borderLeft: "1px solid #d1d5db",
    padding: "4px 10px",
    fontSize: 14,
    cursor: "pointer",
    color: "#9ca3af",
    lineHeight: 1,
  },
  modeToggle: { display: "flex", gap: 4 },
  modeBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 10px",
    fontSize: 11,
    fontWeight: 600,
    cursor: "pointer",
  },
  modeBtnActive: {
    background: "#2563eb",
    color: "#fff",
    borderColor: "#2563eb",
  },
  jsonArea: {
    width: "100%",
    minHeight: 140,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: 8,
    fontFamily: "monospace",
    fontSize: 12,
    boxSizing: "border-box",
    resize: "vertical",
  },
  actions: {
    display: "flex",
    gap: 8,
    marginTop: 10,
    justifyContent: "flex-end",
  },
  runBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
  },
  saveBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    fontSize: 12,
    cursor: "pointer",
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    fontSize: 12,
    cursor: "pointer",
  },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
  },
  eventList: {
    fontFamily: "monospace",
    fontSize: 11,
    maxHeight: 160,
    overflowY: "auto",
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    padding: 8,
    background: "#f9fafb",
  },
  eventRow: {
    display: "flex",
    gap: 8,
    padding: "1px 0",
  },
  eventType: { color: "#2563eb", fontWeight: 700, minWidth: 80 },
  eventNode: { color: "#6b7280" },
  resultBox: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    overflowX: "auto",
    margin: 0,
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
  },
};
