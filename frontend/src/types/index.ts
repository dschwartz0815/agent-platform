// ---------------------------------------------------------------------------
// Identity / workspaces (multi-tenancy from AD groups)
// ---------------------------------------------------------------------------

export type WorkspaceRole = "viewer" | "editor" | "admin" | "owner";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: string;
  role: WorkspaceRole; // caller's effective role, derived from AD groups
}

export interface Me {
  id: string;
  email: string;
  display_name: string;
  ad_groups: string[];
  workspaces: Workspace[];
}

export interface GroupMapping {
  id: string;
  org_id: string;
  ad_group: string;
  role: WorkspaceRole;
  created_at: string;
}

export interface CatalogEntry {
  id: string;
  entry_type: "agent" | "mcp_server";
  name: string;
  description: string | null;
  tags: string[] | null;
  published_at: string | null;
  workspace_id: string;
  workspace_name: string;
  workspace_slug: string;
  owned_by_caller_workspace: boolean;
  agent_type: string | null;
  model: string | null;
  transport: string | null;
  tool_count: number | null;
}

export type Visibility = "private" | "catalog";

export interface GraphNode {
  id: string;
  node_key: string;
  node_type: "llm" | "agent" | "mcp_tool" | "router" | "a2a";
  label: string;
  ref_id: string | null;
  position_x: number;
  position_y: number;
  config_json: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source_node_key: string;
  target_node_key: string;
  condition: string | null;
}

export interface Graph {
  id: string;
  name: string;
  description: string | null;
  version: number;
  parent_graph_id: string | null;
  created_by: string;
  org_id: string;
  definition_json: Record<string, unknown>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  created_at: string;
  updated_at: string;
  slug: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  latest_published_version_id: string | null;
  latest_version_number: number | null;
  retention_days: number;
  test_examples: unknown[] | null;
}

export interface GraphSummary {
  id: string;
  name: string;
  description: string | null;
  version: number;
  parent_graph_id: string | null;
  created_by: string;
  org_id: string;
  created_at: string;
  updated_at: string;
  slug: string | null;
  latest_version_number: number | null;
}

export interface MCPTool {
  name: string;
  description: string | null;
  input_schema: Record<string, unknown>;
}

export interface MCPServer {
  id: string;
  name: string;
  description: string | null;
  transport: "http" | "stdio";
  url: string | null;
  command: string | null;
  args: string[] | null;
  env_vars: Record<string, string> | null;
  tools_json: MCPTool[] | null;
  visibility: Visibility;
  tags: string[] | null;
  published_at: string | null;
  source_id: string | null;
  created_by: string;
  org_id: string;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  agent_type: "llm" | "http";
  model: string | null;
  system_prompt: string | null;
  url: string | null;
  agent_card_url: string | null;
  agent_card_json: Record<string, unknown> | null;
  visibility: Visibility;
  tags: string[] | null;
  published_at: string | null;
  source_id: string | null;
  created_by: string;
  org_id: string;
  created_at: string;
}

export interface RunEvent {
  event: "node_start" | "node_end" | "token" | "done" | "error";
  node: string | null;
  data: unknown;
}

// ---------------------------------------------------------------------------
// Registry create/update wire types — mirror backend Pydantic schemas
// ---------------------------------------------------------------------------

export interface AgentCreate {
  name: string;
  description?: string | null;
  agent_type: "llm" | "http";
  model?: string | null;
  system_prompt?: string | null;
  url?: string | null;
  agent_card_url?: string | null;
}

export interface AgentUpdate {
  name?: string;
  description?: string | null;
  model?: string | null;
  system_prompt?: string | null;
  url?: string | null;
  agent_card_url?: string | null;
}

export interface MCPServerCreate {
  name: string;
  description?: string | null;
  transport: "http" | "stdio";
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  env_vars?: Record<string, string> | null;
}

export interface MCPServerUpdate {
  name?: string;
  description?: string | null;
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  env_vars?: Record<string, string> | null;
}

export interface Usage {
  graph_id: string;
  graph_name: string;
  node_key: string;
}

export interface GraphVersionSummary {
  id: string;
  version: number;
  published_by: string;
  published_at: string;
  notes: string | null;
}

export interface GraphVersion extends GraphVersionSummary {
  graph_id: string;
  definition_json: Record<string, unknown>;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
}

export interface GraphPublishBody {
  notes?: string | null;
}

export interface RunStep {
  id: string;
  node_key: string;
  node_type: string;
  status: "running" | "succeeded" | "failed" | "skipped";
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  input_snapshot: Record<string, unknown> | null;
  output_snapshot: Record<string, unknown> | null;
  token_usage: Record<string, number> | null;
  error_message: string | null;
  step_order: number;
}

export interface RunSummary {
  id: string;
  graph_id: string;
  graph_version_id: string | null;
  trigger_source: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  token_usage: Record<string, number> | null;
  error_message: string | null;
  input_preview: string;
}

export interface Run {
  id: string;
  graph_id: string;
  graph_version_id: string | null;
  trigger_source: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  token_usage: Record<string, number> | null;
  steps: RunStep[];
}

export interface TestExample {
  id: string;
  name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  created_at: string;
}

export interface TestExampleCreate {
  name: string;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
}

export interface ApiKey {
  id: string;
  org_id: string;
  name: string;
  key_prefix: string;
  key_last4: string;
  scopes: string[]; // ["*"] or list of graph UUIDs
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreate {
  name: string;
  scopes: string[];
}

export interface ApiKeyCreated extends ApiKey {
  key: string; // plaintext, shown ONCE
}
