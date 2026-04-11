import type { ChangeEvent } from "react";

/**
 * Generates a form from a JSON Schema object.
 *
 * Supported field types (matching JsonSchemaEditor's visual-mode subset):
 *   - string, number, integer, boolean
 *   - string enum (rendered as select)
 *   - array of primitive strings (rendered as comma-separated tag input)
 *   - one level of nested object (rendered as fieldset)
 *
 * Unsupported features (oneOf, allOf, $ref, deep nesting) fall back to a JSON textarea.
 */

interface Props {
  schema: Record<string, unknown> | null;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
}

type SchemaField = {
  name: string;
  type: "string" | "number" | "integer" | "boolean" | "enum" | "array" | "object" | "unknown";
  required: boolean;
  description?: string;
  enumValues?: string[];
  arrayItemType?: string;
  nestedProperties?: Record<string, unknown>;
};

function extractFields(schema: Record<string, unknown> | null): SchemaField[] {
  if (!schema || schema.type !== "object") return [];
  const props = (schema.properties as Record<string, Record<string, unknown>>) ?? {};
  const required = new Set((schema.required as string[]) ?? []);
  return Object.entries(props).map(([name, def]) => {
    const typeStr = def.type as string | undefined;
    let type: SchemaField["type"] = "unknown";
    if (def.enum) type = "enum";
    else if (typeStr === "array") type = "array";
    else if (typeStr === "object") type = "object";
    else if (typeStr === "integer") type = "integer";
    else if (typeStr === "number") type = "number";
    else if (typeStr === "boolean") type = "boolean";
    else if (typeStr === "string") type = "string";

    return {
      name,
      type,
      required: required.has(name),
      description: def.description as string | undefined,
      enumValues: (def.enum as string[]) ?? undefined,
      arrayItemType: type === "array"
        ? ((def.items as Record<string, unknown>)?.type as string)
        : undefined,
      nestedProperties: type === "object"
        ? (def.properties as Record<string, unknown>)
        : undefined,
    };
  });
}

export function SchemaFormGenerator({ schema, value, onChange, disabled }: Props) {
  const fields = extractFields(schema);

  // If schema is empty or unsupported, fall back to JSON textarea
  if (fields.length === 0 || !schema) {
    return (
      <div>
        <div style={styles.fallbackNote}>
          No schema defined — edit input as raw JSON.
        </div>
        <textarea
          style={styles.jsonArea}
          value={JSON.stringify(value, null, 2)}
          onChange={(e) => {
            try {
              onChange(JSON.parse(e.target.value));
            } catch {
              // Invalid JSON — ignore until valid
            }
          }}
          disabled={disabled}
        />
      </div>
    );
  }

  const setField = (name: string, v: unknown) => {
    onChange({ ...value, [name]: v });
  };

  return (
    <div>
      {fields.map((field) => (
        <FieldRow
          key={field.name}
          field={field}
          value={value[field.name]}
          onChange={(v) => setField(field.name, v)}
          disabled={disabled}
        />
      ))}
    </div>
  );
}

function FieldRow({
  field,
  value,
  onChange,
  disabled,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
}) {
  const handleText = (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    onChange(e.target.value);
  };
  const handleNumber = (e: ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    if (v === "") { onChange(undefined); return; }
    onChange(field.type === "integer" ? parseInt(v, 10) : parseFloat(v));
  };
  const handleBool = (e: ChangeEvent<HTMLInputElement>) => onChange(e.target.checked);

  return (
    <div style={styles.field}>
      <label style={styles.label}>
        {field.name}
        {field.required && <span style={styles.required}> *</span>}
      </label>
      {field.description && <div style={styles.hint}>{field.description}</div>}

      {field.type === "string" && (
        <input style={styles.input} type="text" value={(value as string) ?? ""} onChange={handleText} disabled={disabled} />
      )}
      {(field.type === "number" || field.type === "integer") && (
        <input style={styles.input} type="number" value={(value as number) ?? ""} onChange={handleNumber} disabled={disabled} />
      )}
      {field.type === "boolean" && (
        <label style={styles.checkboxRow}>
          <input type="checkbox" checked={Boolean(value)} onChange={handleBool} disabled={disabled} />
          <span>{field.description ?? field.name}</span>
        </label>
      )}
      {field.type === "enum" && (
        <select
          style={styles.input}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        >
          <option value="">— select —</option>
          {(field.enumValues ?? []).map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      )}
      {field.type === "array" && (
        <input
          style={styles.input}
          type="text"
          placeholder="comma-separated values"
          value={Array.isArray(value) ? (value as string[]).join(", ") : ""}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
          disabled={disabled}
        />
      )}
      {field.type === "object" && field.nestedProperties && (
        <fieldset style={styles.fieldset}>
          <SchemaFormGenerator
            schema={{ type: "object", properties: field.nestedProperties }}
            value={(value as Record<string, unknown>) ?? {}}
            onChange={onChange as (v: Record<string, unknown>) => void}
            disabled={disabled}
          />
        </fieldset>
      )}
      {field.type === "unknown" && (
        <div style={styles.hint}>Unsupported field type — edit via JSON mode.</div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  field: { marginBottom: 12 },
  label: {
    display: "block",
    fontSize: 11,
    fontWeight: 700,
    color: "#374151",
    marginBottom: 3,
  },
  required: { color: "#dc2626" },
  hint: { fontSize: 11, color: "#6b7280", marginBottom: 3 },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "6px 10px",
    fontSize: 13,
    boxSizing: "border-box",
    fontFamily: "system-ui, sans-serif",
  },
  checkboxRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 13,
    color: "#374151",
  },
  fieldset: {
    border: "1px solid #e5e7eb",
    borderRadius: 5,
    padding: 10,
    marginTop: 4,
  },
  jsonArea: {
    width: "100%",
    minHeight: 160,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: 8,
    fontFamily: "monospace",
    fontSize: 12,
    boxSizing: "border-box",
    resize: "vertical",
  },
  fallbackNote: {
    fontSize: 11,
    color: "#6b7280",
    marginBottom: 6,
    fontStyle: "italic",
  },
};
