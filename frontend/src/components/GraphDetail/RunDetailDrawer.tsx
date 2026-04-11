import { useQuery } from "@tanstack/react-query";
import { getRun } from "../../api/client";
import { Drawer } from "../shared/Drawer";
import type { Run, RunStep } from "../../types";

interface Props {
  runId: string | null;
  onClose: () => void;
}

export function RunDetailDrawer({ runId, onClose }: Props) {
  const { data: run, isLoading } = useQuery<Run>({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: Boolean(runId),
  });

  return (
    <Drawer open={Boolean(runId)} title="Run detail" onClose={onClose}>
      {isLoading && <div>Loading…</div>}
      {run && (
        <div>
          <section style={styles.section}>
            <div style={styles.sectionLabel}>Summary</div>
            <Row label="Run ID" value={<code style={styles.code}>{run.id}</code>} />
            <Row label="Status" value={run.status} />
            <Row label="Trigger" value={<code style={styles.code}>{run.trigger_source}</code>} />
            <Row label="Duration" value={run.duration_ms != null ? `${run.duration_ms}ms` : "—"} />
            <Row label="Started" value={new Date(run.started_at).toLocaleString()} />
            {run.graph_version_id && (
              <Row label="Version" value={<code style={styles.code}>{run.graph_version_id}</code>} />
            )}
            {run.token_usage && (
              <Row
                label="Tokens"
                value={
                  <span>
                    in {run.token_usage.input_tokens ?? 0} · out {run.token_usage.output_tokens ?? 0}
                    {(run.token_usage.cache_read_input_tokens ?? 0) > 0 &&
                      <> · cache read {run.token_usage.cache_read_input_tokens}</>}
                  </span>
                }
              />
            )}
          </section>

          {run.error_message && (
            <section style={styles.section}>
              <div style={styles.sectionLabel}>Error</div>
              <pre style={styles.errorBox}>{run.error_message}</pre>
            </section>
          )}

          <section style={styles.section}>
            <div style={styles.sectionLabel}>Input</div>
            <pre style={styles.jsonBox}>{JSON.stringify(run.input_json, null, 2)}</pre>
          </section>

          {run.output_json && (
            <section style={styles.section}>
              <div style={styles.sectionLabel}>Output</div>
              <pre style={styles.jsonBox}>{JSON.stringify(run.output_json, null, 2)}</pre>
            </section>
          )}

          <section style={styles.section}>
            <div style={styles.sectionLabel}>Steps ({run.steps.length})</div>
            {run.steps.length === 0 ? (
              <div style={styles.emptyStep}>No steps recorded for this run.</div>
            ) : (
              <div>
                {run.steps.map((s) => <StepCard key={s.id} step={s} />)}
              </div>
            )}
          </section>
        </div>
      )}
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

function StepCard({ step }: { step: RunStep }) {
  const barWidth = Math.min(100, Math.max(2, (step.duration_ms ?? 0) / 20));
  const statusColor = step.status === "succeeded" ? "#16a34a" : step.status === "failed" ? "#dc2626" : "#6b7280";
  return (
    <div style={styles.stepCard}>
      <div style={styles.stepHeader}>
        <code style={styles.stepName}>{step.node_key}</code>
        <span style={styles.stepType}>{step.node_type}</span>
        <span style={{ ...styles.stepStatus, color: statusColor }}>{step.status}</span>
        <span style={styles.stepDuration}>{step.duration_ms != null ? `${step.duration_ms}ms` : "—"}</span>
      </div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.bar, width: `${barWidth}%`, background: statusColor }} />
      </div>
      {step.token_usage && (step.token_usage.input_tokens ?? 0) + (step.token_usage.output_tokens ?? 0) > 0 && (
        <div style={styles.stepTokens}>
          tokens: in {step.token_usage.input_tokens ?? 0} · out {step.token_usage.output_tokens ?? 0}
        </div>
      )}
      {step.error_message && (
        <pre style={styles.stepError}>{step.error_message}</pre>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  section: { marginBottom: 18 },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 8,
  },
  row: {
    display: "flex",
    gap: 12,
    padding: "5px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  rowLabel: { flexShrink: 0, width: 80, color: "#6b7280", fontSize: 12 },
  rowValue: { color: "#111827", wordBreak: "break-all", flex: 1 },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
  },
  jsonBox: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    maxHeight: 200,
    overflow: "auto",
    margin: 0,
  },
  errorBox: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    margin: 0,
    whiteSpace: "pre-wrap",
  },
  stepCard: {
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    padding: 10,
    marginBottom: 6,
    background: "#fff",
  },
  stepHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 6,
    fontSize: 12,
  },
  stepName: {
    fontFamily: "monospace",
    fontSize: 12,
    fontWeight: 700,
    color: "#111827",
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
  },
  stepType: { color: "#6b7280", fontSize: 11 },
  stepStatus: { fontSize: 10, fontWeight: 700, textTransform: "uppercase" },
  stepDuration: { marginLeft: "auto", color: "#9ca3af", fontSize: 11 },
  barTrack: {
    width: "100%",
    height: 4,
    background: "#f3f4f6",
    borderRadius: 2,
    overflow: "hidden",
  },
  bar: { height: "100%" },
  stepTokens: {
    fontSize: 10,
    color: "#6b7280",
    marginTop: 4,
    fontFamily: "monospace",
  },
  stepError: {
    fontSize: 11,
    color: "#b91c1c",
    marginTop: 6,
    padding: 6,
    background: "#fef2f2",
    borderRadius: 3,
    whiteSpace: "pre-wrap",
    margin: "6px 0 0",
  },
  emptyStep: { color: "#9ca3af", fontSize: 12, fontStyle: "italic" },
};
