import { useRef, useState } from "react";
import { streamRun } from "../../api/client";

interface Props {
  graphId: string;
}

interface LogLine {
  type: "node_start" | "token" | "node_end" | "done" | "error" | "info";
  node?: string | null;
  text: string;
}

interface FinalResult {
  riskLevel: "high" | "medium" | "low" | null;
  confidence: number | null;
  report: string | null;
  rawContext: Record<string, unknown>;
}

const DEFAULT_INPUT = JSON.stringify(
  {
    title: "Migrate payments-service to PostgreSQL 16",
    description:
      "Upgrading the payments DB from Postgres 14 to 16 with a zero-downtime blue/green migration. Includes schema changes to the transactions table.",
    affected_services: ["payments-service", "ledger-service"],
    proposed_window: "Saturday 02:00–04:00 UTC",
  },
  null,
  2
);

export function RunPanel({ graphId }: Props) {
  const [inputText, setInputText] = useState(DEFAULT_INPUT);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<LogLine[]>([]);
  const [result, setResult] = useState<FinalResult | null>(null);
  const [showLog, setShowLog] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const contextRef = useRef<Record<string, unknown>>({});

  const appendLog = (line: LogLine) => setLog((prev) => [...prev, line]);

  const run = () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(inputText);
    } catch {
      appendLog({ type: "error", text: "Input must be valid JSON" });
      return;
    }

    setLog([{ type: "info", text: "Starting run…" }]);
    setResult(null);
    setShowLog(true);
    setRunning(true);
    contextRef.current = {};

    abortRef.current = streamRun(
      graphId,
      parsed,
      (evt) => {
        if (evt.event === "node_start") {
          appendLog({ type: "node_start", node: evt.node, text: `▶ ${evt.node}` });

        } else if (evt.event === "token") {
          // Accumulate tokens onto the last token line for the same node
          setLog((prev) => {
            const last = prev[prev.length - 1];
            if (last?.type === "token" && last.node === evt.node) {
              return [...prev.slice(0, -1), { ...last, text: last.text + String(evt.data) }];
            }
            return [...prev, { type: "token", node: evt.node, text: String(evt.data) }];
          });

        } else if (evt.event === "node_end") {
          const data = evt.data as Record<string, unknown> | null;

          // Accumulate context outputs for the final result panel
          if (data?.context) {
            contextRef.current = { ...contextRef.current, ...(data.context as Record<string, unknown>) };
          }
          if (data?.message_text) {
            contextRef.current = { ...contextRef.current, [`__msg_${evt.node}`]: data.message_text };
          }

          // Only log non-empty, human-readable node_end events
          if (data && Object.keys(data).length > 0) {
            const summary = _summarizeNodeEnd(evt.node, data);
            if (summary) appendLog({ type: "node_end", node: evt.node, text: summary });
          } else {
            appendLog({ type: "node_end", node: evt.node, text: `✓ ${evt.node}` });
          }

        } else if (evt.event === "error") {
          appendLog({ type: "error", text: `Error: ${evt.data}` });
        }
      },
      () => {
        appendLog({ type: "done", text: "── Run complete ──" });
        setRunning(false);

        // Build the final result from accumulated context
        const ctx = contextRef.current;
        const classification = ctx.classification as Record<string, unknown> | undefined;
        const reportMsg = (ctx[`__msg_summarize`] as string | undefined) ?? null;

        setResult({
          riskLevel: (classification?.risk_level as "high" | "medium" | "low") ?? null,
          confidence: typeof classification?.confidence === "number" ? classification.confidence : null,
          report: reportMsg,
          rawContext: ctx,
        });
        setShowLog(false); // switch to report view after done
      },
      (err) => {
        appendLog({ type: "error", text: `Error: ${err}` });
        setRunning(false);
      }
    );
  };

  const stop = () => {
    abortRef.current?.abort();
    setRunning(false);
    appendLog({ type: "info", text: "── Cancelled ──" });
  };

  return (
    <div style={styles.container}>
      {/* Input section */}
      <div style={styles.section}>
        <label style={styles.label}>Input JSON</label>
        <textarea
          style={styles.textarea}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={running}
        />
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button style={styles.runBtn} onClick={run} disabled={running}>
          {running ? "Running…" : "▶ Run"}
        </button>
        {running && (
          <button style={styles.stopBtn} onClick={stop}>
            ■ Stop
          </button>
        )}
        {(log.length > 0 || result) && (
          <button
            style={styles.clearBtn}
            onClick={() => { setLog([]); setResult(null); }}
            disabled={running}
          >
            Clear
          </button>
        )}
        {result && !running && (
          <button
            style={{ ...styles.clearBtn, fontSize: 11 }}
            onClick={() => setShowLog((v) => !v)}
          >
            {showLog ? "Show report" : "Show log"}
          </button>
        )}
      </div>

      {/* Log — shown during run or when user toggles it */}
      {(running || showLog) && log.length > 0 && (
        <div style={styles.logBox}>
          {log.map((line, i) => (
            <div key={i} style={{ ...styles.logLine, ...logLineStyle(line.type) }}>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {line.text}
              </pre>
            </div>
          ))}
        </div>
      )}

      {/* Final report — shown when run is done and log is hidden */}
      {result && !running && !showLog && (
        <ResultPanel result={result} />
      )}

      {/* Placeholder */}
      {!running && log.length === 0 && !result && (
        <div style={{ color: "#9ca3af", fontSize: 12 }}>
          Run output will appear here.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result panel — renders structured output + markdown report
// ---------------------------------------------------------------------------

function ResultPanel({ result }: { result: FinalResult }) {
  return (
    <div style={{ overflowY: "auto", flex: 1 }}>
      {result.riskLevel && (
        <div style={{ marginBottom: 12 }}>
          <RiskBadge level={result.riskLevel} confidence={result.confidence} />
        </div>
      )}

      {result.report ? (
        <MarkdownReport text={result.report} />
      ) : (
        <div style={{ color: "#9ca3af", fontSize: 12 }}>
          No report generated. Run a graph that includes a summarize node.
        </div>
      )}
    </div>
  );
}

function RiskBadge({ level, confidence }: { level: string; confidence: number | null }) {
  const colors: Record<string, { bg: string; text: string; border: string }> = {
    high:   { bg: "#fef2f2", text: "#dc2626", border: "#fca5a5" },
    medium: { bg: "#fffbeb", text: "#d97706", border: "#fcd34d" },
    low:    { bg: "#f0fdf4", text: "#16a34a", border: "#86efac" },
  };
  const c = colors[level.toLowerCase()] ?? colors.medium;
  const pct = confidence !== null ? ` · ${Math.round(confidence * 100)}% confidence` : "";
  return (
    <div style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "4px 12px",
      borderRadius: 20,
      background: c.bg,
      border: `1px solid ${c.border}`,
      color: c.text,
      fontWeight: 700,
      fontSize: 13,
    }}>
      <span style={{ fontSize: 14 }}>
        {level === "high" ? "🔴" : level === "medium" ? "🟡" : "🟢"}
      </span>
      {level.toUpperCase()} RISK{pct}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simple markdown renderer — handles the specific patterns the seed graph uses
// ---------------------------------------------------------------------------

function MarkdownReport({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  const bullets: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (!bullets.length) return;
    out.push(
      <ul key={key++} style={{ margin: "3px 0 8px 16px", padding: 0 }}>
        {bullets.splice(0).map((b, j) => (
          <li key={j} style={{ marginBottom: 2, fontSize: 13, lineHeight: 1.5 }}>
            <span dangerouslySetInnerHTML={{ __html: inlineMd(b) }} />
          </li>
        ))}
      </ul>
    );
  };

  for (const line of lines) {
    if (line.startsWith("## ")) {
      flushBullets();
      out.push(
        <h2 key={key++} style={{ fontSize: 15, fontWeight: 700, margin: "14px 0 5px", color: "#111827", borderBottom: "1px solid #e5e7eb", paddingBottom: 3 }}>
          {line.slice(3)}
        </h2>
      );
    } else if (line.startsWith("### ")) {
      flushBullets();
      out.push(
        <h3 key={key++} style={{ fontSize: 13, fontWeight: 700, margin: "10px 0 3px", color: "#374151" }}>
          {line.slice(4)}
        </h3>
      );
    } else if (line.startsWith("- ")) {
      bullets.push(line.slice(2));
    } else if (line.trim()) {
      flushBullets();
      out.push(
        <p key={key++} style={{ margin: "3px 0", fontSize: 13, lineHeight: 1.6 }}>
          <span dangerouslySetInnerHTML={{ __html: inlineMd(line) }} />
        </p>
      );
    } else {
      flushBullets();
    }
  }
  flushBullets();

  return <div style={{ fontFamily: "system-ui, sans-serif" }}>{out}</div>;
}

function inlineMd(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, '<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px;font-family:monospace;font-size:11px">$1</code>');
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _summarizeNodeEnd(nodeName: string | null, data: Record<string, unknown>): string {
  const ctx = data.context as Record<string, unknown> | undefined;
  const msgText = data.message_text as string | undefined;
  const parts: string[] = [`✓ ${nodeName}`];

  if (ctx?.classification) {
    const c = ctx.classification as Record<string, unknown>;
    parts.push(`→ ${String(c.risk_level ?? "").toUpperCase()} (${Math.round(Number(c.confidence ?? 0) * 100)}%)`);
  }
  if (ctx?.current_route) {
    parts.push(`→ routing to: ${ctx.current_route}`);
  }
  if (ctx?.dependencies) {
    const d = ctx.dependencies;
    if (Array.isArray(d)) {
      parts.push(`→ ${d.length} service(s) resolved`);
    } else if (typeof d === "object" && d !== null) {
      const deps = d as Record<string, unknown>;
      if (deps.found !== false) {
        const down = (deps.downstream as string[] | undefined)?.length ?? 0;
        parts.push(`→ ${deps.service} (${down} downstream)`);
      }
    }
  }
  if (msgText) {
    // Show only the first line as a preview in the log
    const firstLine = msgText.split("\n").find((l) => l.trim());
    if (firstLine) parts.push(`→ ${firstLine.slice(0, 80)}${firstLine.length > 80 ? "…" : ""}`);
  }

  return parts.join(" ");
}

function logLineStyle(type: LogLine["type"]): React.CSSProperties {
  switch (type) {
    case "node_start": return { color: "#6366f1", fontWeight: 600 };
    case "node_end":   return { color: "#059669" };
    case "token":      return { color: "#1f2937" };
    case "error":      return { color: "#dc2626", fontWeight: 600 };
    case "done":       return { color: "#9ca3af", fontStyle: "italic" };
    default:           return { color: "#6b7280" };
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: { padding: 16, display: "flex", flexDirection: "column", height: "100%", overflowY: "auto" },
  section:   { marginBottom: 12 },
  label:     { fontSize: 11, fontWeight: 600, color: "#374151", display: "block", marginBottom: 4 },
  textarea:  {
    width: "100%", height: 120, border: "1px solid #d1d5db", borderRadius: 6,
    padding: 8, fontSize: 11, fontFamily: "monospace", boxSizing: "border-box", resize: "vertical",
  },
  runBtn:  { background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, padding: "8px 20px", cursor: "pointer", fontWeight: 600, fontSize: 13 },
  stopBtn: { background: "#dc2626", color: "#fff", border: "none", borderRadius: 6, padding: "8px 16px", cursor: "pointer", fontWeight: 600 },
  clearBtn: { background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: 6, padding: "8px 12px", cursor: "pointer", fontSize: 12 },
  logBox: {
    border: "1px solid #e5e7eb", borderRadius: 6, padding: 10,
    background: "#f9fafb", overflowY: "auto", maxHeight: 300,
    fontFamily: "monospace", fontSize: 12, marginBottom: 12,
  },
  logLine: { marginBottom: 4 },
};
