import axios from "axios";
import { identityHeaders } from "../identity";
import type {
  Agent,
  AgentCreate,
  AgentUpdate,
  ApiKey,
  ApiKeyCreate,
  ApiKeyCreated,
  CatalogEntry,
  Graph,
  GroupMapping,
  Me,
  Workspace,
  WorkspaceRole,
  GraphPublishBody,
  GraphSummary,
  GraphVersion,
  GraphVersionSummary,
  MCPServer,
  MCPServerCreate,
  MCPServerUpdate,
  MCPTool,
  Run,
  RunSummary,
  TestExample,
  TestExampleCreate,
  Usage,
} from "../types";

const api = axios.create({
  baseURL: "/api/v1",
});

// Attach identity (dev simulation) + active workspace headers to every call
api.interceptors.request.use((config) => {
  for (const [k, v] of Object.entries(identityHeaders())) {
    config.headers.set(k, v);
  }
  return config;
});

// Identity / workspaces
export const getMe = (): Promise<Me> => api.get("/me").then((r) => r.data);

export const listWorkspaces = (): Promise<Workspace[]> =>
  api.get("/workspaces").then((r) => r.data);

export const getCurrentWorkspace = (): Promise<Workspace> =>
  api.get("/workspaces/current").then((r) => r.data);

export const createWorkspace = (body: {
  name: string;
  slug: string;
  description?: string | null;
  owner_group: string;
}): Promise<Workspace> => api.post("/workspaces", body).then((r) => r.data);

export const listGroupMappings = (workspaceId: string): Promise<GroupMapping[]> =>
  api.get(`/workspaces/${workspaceId}/group-mappings`).then((r) => r.data);

export const createGroupMapping = (
  workspaceId: string,
  body: { ad_group: string; role: WorkspaceRole }
): Promise<GroupMapping> =>
  api.post(`/workspaces/${workspaceId}/group-mappings`, body).then((r) => r.data);

export const deleteGroupMapping = (workspaceId: string, mappingId: string): Promise<void> =>
  api.delete(`/workspaces/${workspaceId}/group-mappings/${mappingId}`).then(() => undefined);

// Catalog
export const listCatalog = (entryType?: "agent" | "mcp_server"): Promise<CatalogEntry[]> =>
  api
    .get(`/catalog${entryType ? `?entry_type=${entryType}` : ""}`)
    .then((r) => r.data);

export const installCatalogAgent = (id: string): Promise<Agent> =>
  api.post(`/catalog/agents/${id}/install`).then((r) => r.data);

export const installCatalogMCPServer = (id: string): Promise<MCPServer> =>
  api.post(`/catalog/mcp-servers/${id}/install`).then((r) => r.data);

export const publishAgent = (id: string): Promise<Agent> =>
  api.post(`/agents/${id}/publish`).then((r) => r.data);

export const unpublishAgent = (id: string): Promise<Agent> =>
  api.post(`/agents/${id}/unpublish`).then((r) => r.data);

export const publishMCPServer = (id: string): Promise<MCPServer> =>
  api.post(`/mcp-servers/${id}/publish`).then((r) => r.data);

export const unpublishMCPServer = (id: string): Promise<MCPServer> =>
  api.post(`/mcp-servers/${id}/unpublish`).then((r) => r.data);

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

export const patchGraph = (
  id: string,
  body: {
    name?: string;
    description?: string | null;
    slug?: string;
    input_schema?: Record<string, unknown> | null;
    output_schema?: Record<string, unknown> | null;
    retention_days?: number;
  }
): Promise<Graph> => api.patch(`/graphs/${id}`, body).then((r) => r.data);

export const publishGraph = (
  id: string,
  body: GraphPublishBody
): Promise<GraphVersion> => api.post(`/graphs/${id}/publish`, body).then((r) => r.data);

export const listGraphVersions = (id: string): Promise<GraphVersionSummary[]> =>
  api.get(`/graphs/${id}/versions`).then((r) => r.data);

export const getGraphVersion = (id: string, version: number): Promise<GraphVersion> =>
  api.get(`/graphs/${id}/versions/${version}`).then((r) => r.data);

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

export const createAgent = (body: AgentCreate): Promise<Agent> =>
  api.post("/agents/", body).then((r) => r.data);

export const updateAgent = (id: string, body: AgentUpdate): Promise<Agent> =>
  api.patch(`/agents/${id}`, body).then((r) => r.data);

export const deleteAgent = (id: string): Promise<void> =>
  api.delete(`/agents/${id}`).then(() => undefined);

export const refreshAgentCard = (id: string): Promise<Agent> =>
  api.post(`/agents/${id}/refresh-card`).then((r) => r.data);

export const getAgentUsages = (id: string): Promise<Usage[]> =>
  api.get(`/agents/${id}/usages`).then((r) => r.data);

// MCP Servers
export const listMCPServers = (): Promise<MCPServer[]> =>
  api.get("/mcp-servers/").then((r) => r.data);

export const createMCPServer = (body: MCPServerCreate): Promise<MCPServer> =>
  api.post("/mcp-servers/", body).then((r) => r.data);

export const updateMCPServer = (id: string, body: MCPServerUpdate): Promise<MCPServer> =>
  api.patch(`/mcp-servers/${id}`, body).then((r) => r.data);

export const deleteMCPServer = (id: string): Promise<void> =>
  api.delete(`/mcp-servers/${id}`).then(() => undefined);

export const refreshMCPServerTools = (id: string): Promise<{ tools: MCPTool[] }> =>
  api.post(`/mcp-servers/${id}/refresh-tools`).then((r) => r.data);

export const getMCPServerTools = (
  id: string
): Promise<{ tools: MCPTool[] }> =>
  api.get(`/mcp-servers/${id}/tools`).then((r) => r.data);

export const getMCPServerUsages = (id: string): Promise<Usage[]> =>
  api.get(`/mcp-servers/${id}/usages`).then((r) => r.data);

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
    headers: { "Content-Type": "application/json", ...identityHeaders() },
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

// Runs
export const listGraphRuns = (
  graphId: string,
  opts?: { status?: string; limit?: number; offset?: number }
): Promise<RunSummary[]> => {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return api.get(`/graphs/${graphId}/runs${qs ? "?" + qs : ""}`).then((r) => r.data);
};

export const getRun = (runId: string): Promise<Run> =>
  api.get(`/runs/${runId}`).then((r) => r.data);

// Examples
export const createExample = (
  graphId: string,
  body: TestExampleCreate
): Promise<TestExample> =>
  api.post(`/graphs/${graphId}/examples`, body).then((r) => r.data);

export const deleteExample = (graphId: string, exampleId: string): Promise<void> =>
  api.delete(`/graphs/${graphId}/examples/${exampleId}`).then(() => undefined);

// API Keys
export const listApiKeys = (): Promise<ApiKey[]> =>
  api.get("/api-keys").then((r) => r.data);

export const createApiKey = (body: ApiKeyCreate): Promise<ApiKeyCreated> =>
  api.post("/api-keys", body).then((r) => r.data);

export const revokeApiKey = (id: string): Promise<ApiKey> =>
  api.post(`/api-keys/${id}/revoke`).then((r) => r.data);

export const deleteApiKey = (id: string): Promise<void> =>
  api.delete(`/api-keys/${id}`).then(() => undefined);
