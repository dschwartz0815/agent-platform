import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patchGraph } from "../../api/client";
import { Drawer } from "../shared/Drawer";
import { JsonSchemaEditor } from "../shared/JsonSchemaEditor";
import type { Graph } from "../../types";

interface Props {
  open: boolean;
  onClose: () => void;
  graph: Graph;
}

export function SchemasDrawer({ open, onClose, graph }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"input" | "output">("input");
  const [inputSchema, setInputSchema] = useState(graph.input_schema);
  const [outputSchema, setOutputSchema] = useState(graph.output_schema);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setInputSchema(graph.input_schema);
      setOutputSchema(graph.output_schema);
      setBanner(null);
    }
  }, [open, graph.id, graph.input_schema, graph.output_schema]);

  const saveMut = useMutation({
    mutationFn: () =>
      patchGraph(graph.id, {
        input_schema: inputSchema,
        output_schema: outputSchema,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graph.id] });
      setBanner("Schemas saved.");
    },
    onError: () => setBanner("Save failed. Please retry."),
  });

  return (
    <Drawer open={open} title="Schemas" onClose={onClose} width={560}>
      <div style={{ marginBottom: 10, color: "#4b5563", fontSize: 12 }}>
        Define what this graph accepts as input and what it returns as output.
        Schemas drive API documentation, the Test tab form, and request validation.
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 14, borderBottom: "1px solid #e5e7eb" }}>
        <button
          style={{ ...styles.tab, ...(tab === "input" ? styles.tabActive : {}) }}
          onClick={() => setTab("input")}
        >
          Input Schema
        </button>
        <button
          style={{ ...styles.tab, ...(tab === "output" ? styles.tabActive : {}) }}
          onClick={() => setTab("output")}
        >
          Output Schema
        </button>
      </div>

      {tab === "input" && (
        <JsonSchemaEditor value={inputSchema} onChange={setInputSchema} />
      )}
      {tab === "output" && (
        <JsonSchemaEditor value={outputSchema} onChange={setOutputSchema} />
      )}

      {banner && <div style={styles.banner}>{banner}</div>}

      <div style={styles.actions}>
        <button
          style={styles.saveBtn}
          onClick={() => saveMut.mutate()}
          disabled={saveMut.isPending}
        >
          {saveMut.isPending ? "Saving…" : "Save schemas"}
        </button>
      </div>
    </Drawer>
  );
}

const styles: Record<string, React.CSSProperties> = {
  tab: {
    padding: "8px 14px",
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    color: "#6b7280",
  },
  tabActive: {
    color: "#2563eb",
    borderBottom: "2px solid #2563eb",
  },
  actions: {
    marginTop: 16,
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
    display: "flex",
    justifyContent: "flex-end",
  },
  saveBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
  },
  banner: {
    background: "#f0fdf4",
    border: "1px solid #86efac",
    color: "#15803d",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
    marginTop: 10,
  },
};
