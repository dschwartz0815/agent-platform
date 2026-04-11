import axios from "axios";
import type { Agent, Graph, GraphSummary, MCPServer } from "../types";

const api = axios.create({
  baseURL: "/api/v1",
});

// Graphs
export const listGraphs = (): Promise<GraphSummary[]> =>
  api.get("/graphs/").then((r) => r.data);

export const getGraph = (id: string): Promise<Graph> =>
  api.get(`/graphs/${id}`).then((r) => r.data);

export const updateGraph = (
  id: string,
  payload: {
    name?: string;
    description?: string;
    nodes?: Graph["nodes"];
    edges?: Graph["edges"];
  }
): Promise<Graph> => api.put(`/graphs/${id}`, payload).then((r) => r.data);

export const cloneGraph = (id: string): Promise<Graph> =>
  api.post(`/graphs/${id}/clone`).then((r) => r.data);

export const deleteGraph = (id: string): Promise<void> =>
  api.delete(`/graphs/${id}`).then(() => undefined);

export const createGraph = (payload: {
  name: string;
  description?: string;
  nodes?: Graph["nodes"];
  edges?: Graph["edges"];
}): Promise<Graph> => api.post("/graphs/", payload).then((r) => r.data);

// Agents
export const listAgents = (): Promise<Agent[]> =>
  api.get("/agents/").then((r) => r.data);

// MCP Servers
export const listMCPServers = (): Promise<MCPServer[]> =>
  api.get("/mcp-servers/").then((r) => r.data);

export const getMCPServerTools = (
  id: string
): Promise<{ tools: { name: string; description: string }[] }> =>
  api.get(`/mcp-servers/${id}/tools`).then((r) => r.data);

/**
 * Stream a graph run. Returns an AbortController so the caller can cancel.
 * onEvent is called for each SSE payload.
 */
export function streamRun(
  graphId: string,
  input: Record<string, unknown>,
  onEvent: (event: { event: string; node: string | null; data: unknown }) => void,
  onDone: () => void,
  onError: (msg: string) => void
): AbortController {
  const controller = new AbortController();

  fetch(`/api/v1/graphs/${graphId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`);
        return;
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const evt = JSON.parse(line.slice(6));
              onEvent(evt);
              if (evt.event === "done") onDone();
              if (evt.event === "error") onError(evt.data as string);
            } catch {
              // malformed line — skip
            }
          }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return controller;
}
