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
