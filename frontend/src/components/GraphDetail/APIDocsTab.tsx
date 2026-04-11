import { useState } from "react";
import { JsonSchemaEditor } from "../shared/JsonSchemaEditor";
import type { Graph } from "../../types";

interface Props {
  graph: Graph;
}

type CodeLang = "curl" | "python" | "typescript";

export function APIDocsTab({ graph }: Props) {
  const [lang, setLang] = useState<CodeLang>("curl");

  const endpoint = `POST /api/v1/graphs/${graph.id}/run`;
  const sampleInput = _buildSampleInput(graph.input_schema);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section style={styles.endpointCard}>
        <div style={styles.endpointLabel}>Endpoint</div>
        <div style={styles.endpointRow}>
          <span style={styles.method}>POST</span>
          <code style={styles.endpointUrl}>{endpoint}</code>
        </div>
        <div style={styles.modes}>
          <strong>Delivery:</strong> streaming (SSE){" "}
          <span style={{ color: "#9ca3af" }}>
            · sync / async / public endpoints land in later plans
          </span>
        </div>
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Request body</div>
        <JsonSchemaEditor value={graph.input_schema} readOnly />
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Response</div>
        <JsonSchemaEditor value={graph.output_schema} readOnly />
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Example request</div>
        <div style={styles.langTabs}>
          {(["curl", "python", "typescript"] as CodeLang[]).map((l) => (
            <button
              key={l}
              style={{ ...styles.langTab, ...(lang === l ? styles.langTabActive : {}) }}
              onClick={() => setLang(l)}
            >
              {l}
            </button>
          ))}
        </div>
        <pre style={styles.codeBlock}>{_renderSnippet(lang, graph, sampleInput)}</pre>
      </section>
    </div>
  );
}

function _buildSampleInput(schema: Record<string, unknown> | null): Record<string, unknown> {
  if (!schema || schema.type !== "object") return {};
  const props = (schema.properties as Record<string, Record<string, unknown>>) ?? {};
  const result: Record<string, unknown> = {};
  for (const [name, def] of Object.entries(props)) {
    const typeStr = def.type as string | undefined;
    if (def.enum) {
      result[name] = (def.enum as unknown[])[0] ?? "";
    } else if (typeStr === "string") {
      result[name] = `<${name}>`;
    } else if (typeStr === "number" || typeStr === "integer") {
      result[name] = 0;
    } else if (typeStr === "boolean") {
      result[name] = false;
    } else if (typeStr === "array") {
      result[name] = [];
    } else if (typeStr === "object") {
      result[name] = {};
    } else {
      result[name] = null;
    }
  }
  return result;
}

function _renderSnippet(lang: CodeLang, graph: Graph, sampleInput: Record<string, unknown>): string {
  const url = `http://localhost:8000/api/v1/graphs/${graph.id}/run`;

  if (lang === "curl") {
    return [
      "curl -N -X POST \\",
      `  ${url} \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -d '${JSON.stringify({ input: sampleInput })}'`,
    ].join("\n");
  }
  if (lang === "python") {
    return [
      "import httpx, json",
      "",
      "with httpx.stream(",
      `    "POST", "${url}",`,
      `    json=${JSON.stringify({ input: sampleInput }, null, 4).replace(/\n/g, "\n    ")},`,
      "    timeout=None,",
      ") as r:",
      "    for line in r.iter_lines():",
      "        if line.startswith('data: '):",
      "            event = json.loads(line[6:])",
      "            print(event)",
    ].join("\n");
  }
  // typescript
  return [
    `const resp = await fetch("${url}", {`,
    `  method: "POST",`,
    `  headers: { "Content-Type": "application/json" },`,
    `  body: JSON.stringify({ input: ${JSON.stringify(sampleInput, null, 2)} }),`,
    `});`,
    `const reader = resp.body!.getReader();`,
    `const decoder = new TextDecoder();`,
    `while (true) {`,
    `  const { done, value } = await reader.read();`,
    `  if (done) break;`,
    `  const chunk = decoder.decode(value);`,
    `  // parse SSE lines...`,
    `}`,
  ].join("\n");
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  endpointCard: {
    background: "#0f172a",
    color: "#fff",
    borderRadius: 8,
    padding: 16,
  },
  endpointLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 6,
  },
  endpointRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 6,
  },
  method: {
    background: "#166534",
    color: "#fff",
    padding: "2px 8px",
    borderRadius: 3,
    fontSize: 11,
    fontWeight: 800,
  },
  endpointUrl: {
    fontFamily: "monospace",
    fontSize: 13,
    color: "#e2e8f0",
  },
  modes: {
    fontSize: 12,
    color: "#cbd5e1",
    marginTop: 4,
  },
  langTabs: {
    display: "flex",
    gap: 0,
    marginBottom: -1,
  },
  langTab: {
    background: "#f3f4f6",
    border: "1px solid #e5e7eb",
    borderBottom: "none",
    padding: "5px 14px",
    cursor: "pointer",
    fontSize: 11,
    fontWeight: 600,
    color: "#6b7280",
    borderRadius: "4px 4px 0 0",
  },
  langTabActive: {
    background: "#0f172a",
    color: "#fff",
    borderColor: "#0f172a",
  },
  codeBlock: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 12,
    borderRadius: "0 4px 4px 4px",
    fontSize: 11,
    fontFamily: "monospace",
    whiteSpace: "pre",
    overflow: "auto",
    margin: 0,
  },
};
