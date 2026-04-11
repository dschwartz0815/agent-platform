import { useEffect, useState } from "react";

/**
 * Minimal JSON Schema editor supporting the v1 subset:
 *   - object with flat properties
 *   - string, number, integer, boolean
 *   - string enum
 *   - array of primitives
 *   - required field marking
 *   - description per field
 *
 * Has two modes:
 *   - visual: row-per-field editor
 *   - json: raw textarea
 *
 * Props:
 *   - value: current schema (JSON Schema dict)
 *   - onChange: called when the schema changes (visual edits or valid JSON edits)
 *   - readOnly: if true, renders a read-only field table
 */

interface Props {
  value: Record<string, unknown> | null;
  onChange?: (schema: Record<string, unknown>) => void;
  readOnly?: boolean;
}

type FieldType = "string" | "number" | "integer" | "boolean" | "enum" | "array" | "object";

interface FieldRow {
  name: string;
  type: FieldType;
  required: boolean;
  description: string;
  enumValues?: string[];
  arrayItemType?: FieldType;
}

function schemaToRows(schema: Record<string, unknown> | null): FieldRow[] {
  if (!schema || schema.type !== "object") return [];
  const props = (schema.properties as Record<string, Record<string, unknown>>) ?? {};
  const required = new Set((schema.required as string[]) ?? []);
  return Object.entries(props).map(([name, def]) => {
    const type = inferFieldType(def);
    return {
      name,
      type,
      required: required.has(name),
      description: (def.description as string) ?? "",
      enumValues: (def.enum as string[]) ?? undefined,
      arrayItemType: type === "array"
        ? inferFieldType((def.items as Record<string, unknown>) ?? {})
        : undefined,
    };
  });
}

function inferFieldType(def: Record<string, unknown>): FieldType {
  if (def.enum) return "enum";
  const t = def.type as string;
  if (t === "array") return "array";
  if (t === "object") return "object";
  if (t === "integer") return "integer";
  if (t === "number") return "number";
  if (t === "boolean") return "boolean";
  return "string";
}

function rowsToSchema(rows: FieldRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const row of rows) {
    if (!row.name) continue;
    const fieldDef: Record<string, unknown> = {};
    if (row.description) fieldDef.description = row.description;
    switch (row.type) {
      case "enum":
        fieldDef.type = "string";
        fieldDef.enum = row.enumValues ?? [];
        break;
      case "array":
        fieldDef.type = "array";
        fieldDef.items = { type: row.arrayItemType ?? "string" };
        break;
      case "object":
        fieldDef.type = "object";
        fieldDef.properties = {};
        break;
      default:
        fieldDef.type = row.type;
    }
    properties[row.name] = fieldDef;
    if (row.required) required.push(row.name);
  }
  return {
    type: "object",
    ...(required.length ? { required } : {}),
    properties,
  };
}

export function JsonSchemaEditor({ value, onChange, readOnly = false }: Props) {
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [rows, setRows] = useState<FieldRow[]>(() => schemaToRows(value));
  const [jsonText, setJsonText] = useState(() =>
    value ? JSON.stringify(value, null, 2) : ""
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    setRows(schemaToRows(value));
    setJsonText(value ? JSON.stringify(value, null, 2) : "");
  }, [value]);

  const emit = (newRows: FieldRow[]) => {
    setRows(newRows);
    if (onChange) onChange(rowsToSchema(newRows));
  };

  const updateRow = (idx: number, patch: Partial<FieldRow>) => {
    emit(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => emit([...rows, { name: "", type: "string", required: false, description: "" }]);
  const removeRow = (idx: number) => emit(rows.filter((_, i) => i !== idx));

  if (readOnly) {
    return (
      <table style={styles.table}>
        <thead>
          <tr style={styles.headRow}>
            <th style={styles.th}>Field</th>
            <th style={styles.th}>Type</th>
            <th style={styles.th}>Description</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={3} style={styles.emptyCell}>No schema defined.</td></tr>
          ) : rows.map((r, i) => (
            <tr key={i}>
              <td style={styles.td}>
                <code style={styles.code}>{r.name}</code>
                {r.required && <span style={styles.requiredMark}> *</span>}
              </td>
              <td style={{ ...styles.td, fontFamily: "monospace", fontSize: 11, color: "#7c3aed" }}>
                {r.type === "array" ? `${r.arrayItemType ?? "string"}[]` : r.type}
              </td>
              <td style={{ ...styles.td, color: "#4b5563" }}>{r.description || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <div>
      <div style={styles.modeRow}>
        <button
          style={{ ...styles.modeBtn, ...(mode === "visual" ? styles.modeBtnActive : {}) }}
          onClick={() => setMode("visual")}
        >
          Visual
        </button>
        <button
          style={{ ...styles.modeBtn, ...(mode === "json" ? styles.modeBtnActive : {}) }}
          onClick={() => setMode("json")}
        >
          JSON
        </button>
      </div>

      {mode === "visual" ? (
        <div>
          {rows.map((row, i) => (
            <div key={i} style={styles.rowCard}>
              <div style={styles.rowLine}>
                <input
                  style={{ ...styles.input, flex: 2 }}
                  placeholder="field name"
                  value={row.name}
                  onChange={(e) => updateRow(i, { name: e.target.value })}
                />
                <select
                  style={{ ...styles.select, flex: 1 }}
                  value={row.type}
                  onChange={(e) => updateRow(i, { type: e.target.value as FieldType })}
                >
                  <option value="string">string</option>
                  <option value="number">number</option>
                  <option value="integer">integer</option>
                  <option value="boolean">boolean</option>
                  <option value="enum">enum</option>
                  <option value="array">array</option>
                </select>
                <label style={styles.reqCheck}>
                  <input
                    type="checkbox"
                    checked={row.required}
                    onChange={(e) => updateRow(i, { required: e.target.checked })}
                  />
                  required
                </label>
                <button style={styles.removeBtn} onClick={() => removeRow(i)}>×</button>
              </div>
              <input
                style={{ ...styles.input, marginTop: 4, width: "100%" }}
                placeholder="description (optional)"
                value={row.description}
                onChange={(e) => updateRow(i, { description: e.target.value })}
              />
              {row.type === "enum" && (
                <input
                  style={{ ...styles.input, marginTop: 4, width: "100%" }}
                  placeholder="comma-separated enum values"
                  value={(row.enumValues ?? []).join(", ")}
                  onChange={(e) =>
                    updateRow(i, {
                      enumValues: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    })
                  }
                />
              )}
              {row.type === "array" && (
                <select
                  style={{ ...styles.select, marginTop: 4, width: "100%" }}
                  value={row.arrayItemType ?? "string"}
                  onChange={(e) => updateRow(i, { arrayItemType: e.target.value as FieldType })}
                >
                  <option value="string">array of string</option>
                  <option value="number">array of number</option>
                  <option value="integer">array of integer</option>
                  <option value="boolean">array of boolean</option>
                </select>
              )}
            </div>
          ))}
          <button style={styles.addBtn} onClick={addRow}>+ Add field</button>
        </div>
      ) : (
        <div>
          <textarea
            style={styles.jsonArea}
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                setJsonError(null);
                setRows(schemaToRows(parsed));
                if (onChange) onChange(parsed);
              } catch (err) {
                setJsonError((err as Error).message);
              }
            }}
          />
          {jsonError && <div style={styles.errorBox}>{jsonError}</div>}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  modeRow: { display: "flex", gap: 6, marginBottom: 10 },
  modeBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 12px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
  },
  modeBtnActive: { background: "#2563eb", color: "#fff", borderColor: "#2563eb" },
  rowCard: {
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    padding: 8,
    marginBottom: 6,
    background: "#fafafa",
  },
  rowLine: { display: "flex", gap: 6, alignItems: "center" },
  input: {
    border: "1px solid #d1d5db",
    borderRadius: 4,
    padding: "5px 8px",
    fontSize: 12,
    boxSizing: "border-box",
  },
  select: {
    border: "1px solid #d1d5db",
    borderRadius: 4,
    padding: "5px 8px",
    fontSize: 12,
    background: "#fff",
    cursor: "pointer",
  },
  reqCheck: { fontSize: 11, color: "#374151", display: "flex", alignItems: "center", gap: 4 },
  removeBtn: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#dc2626",
    borderRadius: 4,
    padding: "0 8px",
    cursor: "pointer",
    fontWeight: 700,
  },
  addBtn: {
    background: "#f3f4f6",
    border: "1px dashed #d1d5db",
    borderRadius: 5,
    padding: "6px 12px",
    cursor: "pointer",
    fontSize: 12,
    width: "100%",
    marginTop: 4,
  },
  jsonArea: {
    width: "100%",
    minHeight: 200,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: 8,
    fontFamily: "monospace",
    fontSize: 11,
    boxSizing: "border-box",
    resize: "vertical",
  },
  errorBox: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "6px 10px",
    borderRadius: 5,
    fontSize: 11,
    marginTop: 4,
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  headRow: { background: "#f9fafb" },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: 700,
    fontSize: 11,
    color: "#374151",
  },
  td: { padding: "7px 10px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
  },
  requiredMark: { color: "#dc2626", fontWeight: 700, fontSize: 11 },
  emptyCell: { padding: 12, textAlign: "center", color: "#9ca3af", fontSize: 12 },
};
