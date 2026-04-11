# Agent Platform — Integration Guide

> This document is written for a new engineer — human or agent — picking up this codebase with zero context. It's also the guide for integrating the platform into another product, or forking it as a starting point for your own.

If you're going to change code in this repo, **read this document all the way through first.** There are non-obvious design decisions in several places that will trip you up if you skip past them. The spec (`docs/superpowers/specs/2026-04-11-graph-as-api-design.md`) goes deeper on the "why"; this guide goes deeper on the "where" and "how."

---

## Table of contents

1. [Thirty-second version](#thirty-second-version)
2. [What this platform does](#what-this-platform-does)
3. [Running it locally](#running-it-locally)
4. [Architecture](#architecture)
5. [Domain concepts](#domain-concepts)
6. [Database schema](#database-schema)
7. [API surface](#api-surface)
8. [The runtime engine](#the-runtime-engine)
9. [Frontend structure](#frontend-structure)
10. [Security model](#security-model)
11. [Design decisions and gotchas](#design-decisions-and-gotchas)
12. [Extension points](#extension-points)
13. [Testing strategy](#testing-strategy)
14. [How to customize for your platform](#how-to-customize-for-your-platform)
15. [What's next (Plan D)](#whats-next-plan-d)
16. [Reference: file map](#reference-file-map)

---

## Thirty-second version

This is a platform for building **LangGraph-based agent workflows** as a visual graph, persisting every execution with per-node token accounting, and exposing the published versions as **authenticated HTTP APIs** that external services can call. It is a full-stack app: Python/FastAPI backend, Postgres, React/Vite frontend, all orchestrated with docker-compose. There are four planned delivery phases; **A, B, and C are shipped** and live on `main`. Plan D (async jobs + webhooks) is the final phase.

If you're integrating into another platform: the backend is a clean set of REST + SSE endpoints with a full OpenAPI spec at `/docs` — you could replace the React frontend entirely and keep the backend.

If you're extending it: follow the spec-and-plan discipline the project was built with. Every existing feature has a spec in `docs/superpowers/specs/` and a task-by-task plan in `docs/superpowers/plans/`.

---

## What this platform does

Concretely:

1. **A user (builder) draws a graph** in a React Flow canvas. Nodes are LLM calls, router decisions, single MCP tool invocations, A2A agent calls, or full ReAct loops. Edges wire them together; conditional edges from router nodes carry a `condition` label ("high", "medium", "low").
2. **The builder defines schemas** — `input_schema` (what the graph accepts) and `output_schema` (what it returns) as JSON Schema 2020-12. These schemas drive validation, the API docs tab, the interactive test form, and type-safe client snippets.
3. **The builder publishes a version.** The draft becomes `v1` (immutable snapshot). The editor canvas now represents `v(latest+1)` draft. Consumers can pin to `@v1` or ride `latest`.
4. **The builder (or any caller) tests the graph** from the Test tab in the UI or via curl. Every run is persisted as a `runs` row with per-node `run_steps` — timing, token usage, input/output snapshots.
5. **An integration owner generates an API key** scoped to this specific graph (or wildcard). The plaintext key is shown once, bcrypt-hashed at rest, and can be revoked at any time.
6. **Production services call the published graph** as an HTTP endpoint: `POST /v1/run/{org}/{slug}` with `Authorization: Bearer ap_live_...`. Default is sync JSON response; `?mode=stream` returns SSE; (planned) `?mode=async` queues and webhooks back.
7. **Observability**: every call — sync, stream, async, editor-test — writes to the same `runs` table. The Runs tab shows a paginated list with filterable status, click a row to see the waterfall.

This is a **product page for every graph**. It's what GitHub Actions is for CI/CD, what Stripe is for payment routing, what Airtable is for data: a managed layer between "team A built a thing" and "team B needs to call that thing."

---

## Running it locally

Prerequisites: Docker Desktop (or compatible), a code editor, and an Anthropic API key.

```bash
git clone https://github.com/dschwartz0815/agent-platform.git
cd agent-platform
cp .env.example .env                      # fill in ANTHROPIC_API_KEY
docker compose up --build                 # first time: ~2 min; after: ~10s
```

Four services come up:

| Service | Port | What it does |
|---|---|---|
| `postgres` | 5432 | Postgres 16, single database `agent_platform` |
| `backend` | 8000 | FastAPI + uvicorn `--reload`, source volume-mounted |
| `frontend` | 5173 | Vite dev server, source volume-mounted |
| `seed-agent` | 8001 | A small FastAPI app exposing the demo A2A agent (`/.well-known/agent.json` + JSON-RPC `message/send`) |

On startup, the backend:
1. Runs all pending Alembic migrations via `asyncio.to_thread(_run_alembic_upgrade)` in the lifespan context (see `backend/app/main.py`)
2. Runs `seed()` if `DEBUG=true` — idempotently populates a Demo Org, a dev user, a mock stdio MCP server, the demo A2A agent (pointing at `http://seed-agent:8001`), the 5-node `Change Request Risk Analyzer` graph, publishes it as v1, and creates a demo API key (`ap_live_demoseedkey0000000000000000000000`).
3. Serves the FastAPI app.

Open **http://localhost:5173** to see the UI. The OpenAPI docs are at **http://localhost:8000/docs** (Swagger) or **/redoc**.

### Running the test suite

The backend has 80 tests through Plan C. They run against an **in-memory SQLite** database (not Postgres) for speed and isolation, using `Base.metadata.create_all()` + SAVEPOINT-based per-test rollback:

```bash
docker compose exec backend pytest -v            # full suite
docker compose exec backend pytest tests/test_publish.py -v   # one file
docker compose exec backend pytest -k "test_revoke" -v         # pattern
```

The frontend has no automated tests (by spec decision); verification is manual via the browser + curl. Type-check with:

```bash
docker compose exec frontend npx tsc --noEmit
```

---

## Architecture

At the broadest level there are four layers: **persistence**, **domain logic**, **HTTP interface**, and **UI**. Data flows in both directions:

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (React + Vite)                                     │
│  - GraphList, GraphDetail (6 tabs), GraphEditor             │
│  - AgentList, MCPServerList, ApiKeyList                     │
│  - TanStack React Query caches                              │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST + SSE
                           │  Authorization: Bearer ap_live_...
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI (uvicorn, backend container)                       │
│                                                             │
│  Routers:                                                   │
│    /api/v1/graphs, agents, mcp-servers, api-keys, runs      │
│    /api/v1/graphs/{id}/run  (editor test SSE)               │
│    /v1/run/{org}/{slug}     (public, auth required)         │
│                                                             │
│  Middleware: RequestID, CORS, global exception handlers     │
│  Auth: authenticate_api_key dep (bcrypt prefix lookup)      │
│                                                             │
│  Engine:                                                    │
│    runner.py       LangGraph StateGraph + node builders     │
│    persistence.py  run_graph() wrapping stream_graph()      │
│    mcp_client.py   HTTP/SSE + stdio MCP client              │
│                                                             │
│  A2A:                                                       │
│    a2a/card.py     fetch /.well-known/agent.json + send     │
└──────────┬─────────────────────────────────┬────────────────┘
           │                                 │
           │ SQLAlchemy async                │ HTTP/stdio
           ▼                                 ▼
┌──────────────────────┐         ┌──────────────────────────┐
│  Postgres 16         │         │  External systems        │
│                      │         │                          │
│  orgs, users         │         │  seed-agent (FastAPI)    │
│  agents              │         │  /.well-known/agent.json │
│  mcp_servers         │         │                          │
│  graphs              │         │  stdio MCP servers       │
│  graph_versions      │         │  (subprocess per call)   │
│  graph_nodes         │         │                          │
│  graph_edges         │         │  Anthropic API           │
│  runs                │         │  (HTTPS, for LLM nodes)  │
│  run_steps           │         └──────────────────────────┘
│  api_keys            │
└──────────────────────┘
```

### Request flows

**Editor test run** — user hits ▶ in the Test tab:
1. Frontend calls `POST /api/v1/graphs/{id}/run` with optional `?version=N` and JSON body.
2. `routers/execution.py` resolves the graph (and pinned version if any), loads referenced MCP servers and agents, and calls `run_graph(...)`.
3. `engine/persistence.py::run_graph()` creates a `runs` row (status=`running`), yields a `run_started` event, then iterates `engine/runner.py::stream_graph(...)`.
4. `stream_graph` compiles the graph via LangGraph's `StateGraph`, runs `astream_events(version="v2")`, and yields `node_start` / `node_end` / `token` / `done` / `error` events.
5. Per event: `run_graph` writes `run_steps` rows, extracts `last_usage` from LLM node outputs, and passes events through to the caller as SSE frames.
6. On `done` / `error`, `run_graph` finalizes the `runs` row with status, aggregate token usage, duration, final output.
7. Frontend RunPanel (TestTab) consumes the SSE events, renders live progress + accumulated result.

**Public API run** — external service hits `POST /v1/run/acme/change-risk-analyzer`:
1. `routers/public_runs.py` handles the request. First, the `authenticate_api_key` FastAPI dependency runs.
2. Dep extracts `Authorization: Bearer ap_live_...`, computes the 16-char prefix, queries `api_keys WHERE key_prefix = ?`, and for each candidate runs `bcrypt.checkpw(token, key.key_hash)`. On match: reject if revoked, touch `last_used_at`, return the `ApiKey` row. On miss: 401.
3. Handler parses `@vN` suffix from the slug, resolves org + graph (404 if missing or org mismatch with the key).
4. `check_graph_scope(api_key, graph.id)` raises 404 (not 403) if the key's `scopes` list doesn't include this graph and isn't `["*"]`. **This is deliberate** — 404 for scope mismatch avoids giving external callers an enumeration oracle.
5. `validate_against_schema(body.input, graph.input_schema)` raises `SchemaValidationError` on mismatch → 422.
6. Loads pinned `graph_version` definition or falls back to `graph.definition_json`, collects MCP/agent refs, and calls `run_graph(...)` with `trigger_source="api_sync"` or `"api_stream"`.
7. Sync mode: consumes the generator to completion, buffers the final node_end output, returns `{run_id, status, output}` JSON.
8. Stream mode: wraps the generator in a `StreamingResponse` that emits `data: {...}\n\n` SSE frames.

---

## Domain concepts

### Org, User

Single-tenant placeholders in the current implementation. Every row carries `created_by: UUID` (user) and `org_id: UUID` — these fields are present from day one so the platform can add real multi-tenancy without a data migration. The seed creates `Demo Org` (slug=`demo`) and a single dev user. The config module exports `DEV_ORG_ID` and `DEV_USER_ID` as constants that are hardcoded into request handlers — this is the "stubbed auth" point where real auth will plug in later.

### Graph

A directed workflow. Has a mutable draft (the canvas) and zero or more immutable published versions.

- `Graph.definition_json` — denormalized snapshot kept in sync with `graph_nodes`/`graph_edges` rows on every save. The runner reads this directly.
- `Graph.nodes` (list of `GraphNode` rows) and `Graph.edges` (list of `GraphEdge` rows) — normalized source of truth for the editor.
- `Graph.slug` — unique within `(org_id, slug)`; used in public URLs as `/v1/run/{org_slug}/{graph_slug}`.
- `Graph.input_schema` / `Graph.output_schema` — JSON Schema (2020-12 dialect) for the graph's I/O contract. Drive validation, docs, test form generation.
- `Graph.latest_published_version_id` — convenience pointer to the most recent `GraphVersion` row.

### Graph node types

Five types, declared in `runner.py`:

| `node_type` | Purpose | Key config fields |
|---|---|---|
| `llm` | Single Anthropic call, optionally with tool-use for structured output | `model`, `system_prompt`, `tools`, `context_key`, `include_context` |
| `router` | Conditional branching | `source` (dot-path into state), `routes` (value→destination map), `default` |
| `mcp_tool` | Single MCP tool call | `mcp_server_id`, `tool_name`, `arguments`, `output_key` |
| `a2a` | A2A protocol call to an external agent | `agent_id`, `context_key`, `input_template` |
| `agent` | Full ReAct loop with MCP tools | `model`, `system_prompt`, `mcp_server_ids`, `max_iterations` |

Adding a new node type is a ~50 line change in `runner.py` — see [Extension points](#extension-points).

### Graph version

Immutable snapshot of a graph's `definition_json`, `input_schema`, and `output_schema` at publish time. Versions are 1-indexed and unique per graph. When the runner receives a `graph_version_id`, it executes the frozen `definition_json` from that row rather than the live draft.

The draft is never a `graph_version` row — it lives on the `graphs` row itself.

### Run

One execution. Tagged by `trigger_source`:
- `editor_test` — from the in-app Test tab (via `/api/v1/graphs/{id}/run`)
- `api_sync` — from `POST /v1/run/{org}/{slug}` (sync mode)
- `api_stream` — from `POST /v1/run/{org}/{slug}?mode=stream`
- `api_async` — reserved for Plan D

Every run writes a row to `runs`, which holds the input, output, duration, token_usage (aggregated), and status. Runs are scoped to a `graph_id`; optionally pinned to a `graph_version_id` when executed against a published version.

### Run step

One node's execution within a run. Written by `run_graph()` on every `node_start` / `node_end` event pair. Holds per-node timing, `token_usage` (for LLM nodes), input/output snapshots, and a `step_order` integer for stable UI ordering in the waterfall view.

### Agent

External reference to an A2A (agent-to-agent protocol) HTTP agent, or to a built-in LLM agent (no external call — config has `model` + `system_prompt`). HTTP agents are optionally discovered via `/.well-known/agent.json` on registration; the parsed card is cached in `agent_card_json`. The platform **does not host** agents — it registers a pointer and invokes them.

### MCP server

External reference to an MCP (Model Context Protocol) server. Two transports:
- **HTTP/SSE** — URL is the SSE endpoint; the MCP client opens a fresh session per call
- **stdio** — `command` + `args` + `env_vars`; the MCP client spawns a subprocess per call using the stdio MCP transport

Tools are discovered on registration (`list_tools`) and cached in `tools_json`.

### API key

Per-org authentication token for public endpoints. Properties:
- **Plaintext format**: `ap_live_<32 chars of urlsafe_b64>` — returned **once** at creation, never stored.
- **Prefix lookup**: first 16 chars stored indexed as `key_prefix`; the full token is bcrypt-hashed and stored in `key_hash`.
- **Scopes**: JSON array of either `["*"]` (wildcard) or a list of `graph_id` UUID strings.
- **Lifecycle**: `created_at` / `last_used_at` / `revoked_at`.

---

## Database schema

Full diagram (only the Plan A/B/C columns — Plan D will add `webhook_deliveries`):

```
orgs                         users
────────────────────         ────────────────────
id               pk          id               pk
name                         email
slug         unique          display_name
created_at                   org_id           fk→orgs
                             created_at

agents                       mcp_servers
────────────────────         ────────────────────
id               pk          id               pk
name                         name
description                  description
agent_type                   transport
model                        url
system_prompt                command
url                          args             jsonb
agent_card_url               env_vars         jsonb
agent_card_json  jsonb       tools_json       jsonb
created_by       fk→users    created_by       fk→users
org_id           fk→orgs     org_id           fk→orgs
created_at                   created_at

graphs
──────────────────────────────────
id                              pk
name
description
version                         int (editor version counter, unused by API)
parent_graph_id                  fk→graphs     (clone lineage)
slug                             unique per org_id
input_schema                     jsonb (nullable)
output_schema                    jsonb (nullable)
latest_published_version_id      fk→graph_versions
retention_days                   int, default 30
test_examples                    jsonb array of {id, name, input, output, created_at}
created_by                       fk→users
org_id                           fk→orgs
definition_json                  jsonb (denormalized node+edge snapshot)
created_at, updated_at

graph_nodes                     graph_edges
──────────────────             ──────────────────
id                pk            id                pk
graph_id          fk→graphs     graph_id          fk→graphs
                    CASCADE                         CASCADE
node_key          str           source_node_key   str
node_type         str           target_node_key   str
label             str           condition         nullable
ref_id            nullable       (null for unconditional edges;
position_x, y                    set on router outputs: "high"/"medium"/etc)
config_json       jsonb

graph_versions
──────────────────────────
id               pk
graph_id         fk→graphs CASCADE
version          int (1-indexed)
definition_json  jsonb (frozen)
input_schema     jsonb (frozen)
output_schema    jsonb (frozen)
published_by     fk→users
published_at
notes            nullable
UNIQUE (graph_id, version)

runs                             run_steps
──────────────────────────       ──────────────────────────
id                pk             id                pk
graph_id          fk              run_id            fk→runs CASCADE
graph_version_id  fk (nullable)   node_key          str
trigger_source    enum-ish        node_type         str
                  (editor_test /  status            enum-ish
                   api_sync /     started_at
                   api_stream /   completed_at      nullable
                   api_async)     duration_ms       nullable
status            enum-ish        input_snapshot    jsonb nullable
input_json        jsonb           output_snapshot   jsonb nullable
output_json       jsonb nullable  token_usage       jsonb nullable
error_message     nullable        error_message     nullable
started_at                        step_order        int
completed_at      nullable        INDEX (run_id, step_order)
duration_ms       nullable
token_usage       jsonb nullable
INDEX (graph_id, started_at DESC)
INDEX (status)

api_keys
──────────────────────────
id               pk
org_id           fk→orgs CASCADE
name             str
key_prefix       str (16 chars, INDEXED — lookup)
key_hash         text (bcrypt)
key_last4        str (4 chars, UI display only)
scopes           jsonb (["*"] or list of graph_id strings)
created_by       fk→users
created_at
last_used_at     nullable
revoked_at       nullable
INDEX (key_prefix)
INDEX (org_id)
```

Key things to notice:

- **Cascade deletes** — deleting a `graphs` row cascades through `graph_nodes`, `graph_edges`, `graph_versions`, and `runs`/`run_steps`. Deleting an `orgs` row cascades through everything. This is intentional — there is no soft-delete.
- **`graph_version_id` is nullable on `runs`** — draft runs (editor tests against the live canvas) have no version to point at. Published-version runs carry the exact snapshot id.
- **JSON Schema lives as jsonb**, not separate tables. That keeps the editor round-trip simple and the storage shape matches what the runner and docs tabs consume directly.
- **`api_key.key_hash` can't be looked up directly** — bcrypt uses a per-call salt. Hence the `key_prefix` index: lookup candidates by prefix, then `bcrypt.checkpw` each one. Typically one candidate; occasionally two if by vanishingly-low chance two keys share the first 16 characters.

---

## API surface

There are **two HTTP surfaces** with different contracts:

- **`/api/v1/*`** — management API (unauthenticated in dev, stubbed to `DEV_USER_ID`/`DEV_ORG_ID`). This is the only API the frontend talks to. No `/v1/*` prefix inside here.
- **`/v1/*`** — public API for external consumers. Authenticated via `Authorization: Bearer ap_live_...`. Only `/v1/run/*` exists today; reserved for future public endpoints (`/v1/runs/{id}` for polling, etc.).

### Management endpoints

Everything under `/api/v1/`:

```
GET    /graphs/                              — list (GraphSummary[])
POST   /graphs/                              — create
GET    /graphs/{id}                          — full detail with nodes/edges/schemas/versions pointer
PUT    /graphs/{id}                          — full replace (name/desc/nodes/edges)
PATCH  /graphs/{id}                          — partial (slug, schemas, retention)
DELETE /graphs/{id}                          — cascade delete
POST   /graphs/{id}/clone                    — deep copy, sets parent_graph_id
POST   /graphs/{id}/publish                  — freeze draft → new GraphVersion
GET    /graphs/{id}/versions                 — list (GraphVersionSummary[], newest first)
GET    /graphs/{id}/versions/{v}             — full version detail
POST   /graphs/{id}/examples                 — save a test example (stored as jsonb on graphs.test_examples)
DELETE /graphs/{id}/examples/{example_id}    — remove an example
POST   /graphs/{id}/run                      — editor test run (SSE, persists a run row)

GET    /graphs/{id}/runs                     — paginated run list
                                                ?status=<succeeded|failed|running|...>
                                                ?limit=<1..500>&offset=<int>
GET    /runs/{run_id}                        — full run detail with nested steps

GET    /agents/                              — list registered A2A / LLM agents
POST   /agents/                              — create (auto-fetches agent_card on http type)
GET    /agents/{id}                          — read
PATCH  /agents/{id}                          — update
DELETE /agents/{id}
POST   /agents/{id}/refresh-card             — re-probe /.well-known/agent.json
GET    /agents/{id}/usages                   — graphs that reference this agent

GET    /mcp-servers/                         — list registered MCP servers
POST   /mcp-servers/                         — create (auto-probes tools/list)
GET    /mcp-servers/{id}                     — read
PATCH  /mcp-servers/{id}                     — update
DELETE /mcp-servers/{id}
GET    /mcp-servers/{id}/tools               — cached tool list
POST   /mcp-servers/{id}/refresh-tools       — re-probe
GET    /mcp-servers/{id}/usages              — graphs that reference this server

GET    /api-keys                             — list (never returns plaintext)
POST   /api-keys                             — create, returns plaintext ONCE
POST   /api-keys/{id}/revoke                 — mark revoked (still in DB)
DELETE /api-keys/{id}                        — hard delete
```

Error format across everything:
```json
{"error": "human message", "request_id": "uuid"}
```

Validation errors (422 from FastAPI):
```json
{"error": "Validation error", "details": [...field-level list...], "request_id": "uuid"}
```

### Public endpoints

Under `/v1/`:

```
POST /v1/run/{org}/{slug}                    — sync: returns {run_id, status, output}
POST /v1/run/{org}/{slug}?mode=stream        — SSE: same events as editor test
POST /v1/run/{org}/{slug}@v3                 — version-pinned (combine with ?mode=stream)
```

Auth header required on every call:
```
Authorization: Bearer ap_live_<32-char-token>
```

Status code map:
- `200` — success (sync JSON, or 200+SSE body for stream)
- `401` — missing, malformed, invalid, or revoked API key
- `404` — graph not found OR key lacks scope (deliberate — no enumeration oracle)
- `422` — input body fails `input_schema` validation; error body cites the offending field
- `500` — unhandled internal error

SSE event shape (for `?mode=stream`):
```
data: {"event": "run_started", "node": null, "data": {"run_id": "..."}}
data: {"event": "node_start", "node": "classify", "data": null}
data: {"event": "node_end", "node": "classify", "data": {...snapshot...}}
...
data: {"event": "done", "node": null, "data": {}}
```

---

## The runtime engine

Located in `backend/app/engine/`:

### `runner.py` — LangGraph node builders

The core of graph execution. Responsible for:
1. **Compiling a `definition_json` into a LangGraph `StateGraph`** at request time. Not cached — compile-per-request trades a few ms for simplicity and correctness when the draft is edited between calls. Could be cached by version in future.
2. **Implementing each node type** as an `async def node(state) -> dict` closure that returns a partial state update.
3. **Streaming events** via `compiled.astream_events(initial, version="v2")` — yields `on_chain_start` / `on_chain_end` / `on_chat_model_stream` / etc. The runner translates these into our internal event shape and yields them to the caller.

Important implementation details:

- **`AgentState`** is a `TypedDict` with `messages` (annotated with `add_messages` reducer from LangGraph), `input` (original request body), `context` (accumulated tool / agent outputs), `current_route` (router state), and `last_usage` (LLM token usage — see below).
- **LLM nodes** call `_anthropic.messages.create(**params)` directly — not through LangChain's `ChatAnthropic`. This was a deliberate choice to keep the Anthropic tool-use API surface accessible without the LangChain indirection. As a consequence, LangGraph's `on_chat_model_stream` events never fire (that's a LangChain concept), and token streaming isn't currently delivered per-token to the frontend. This is a future upgrade path.
- **Token usage plumbing**: after each `_anthropic.messages.create(...)` call, the node extracts `response.usage` via `_extract_usage()` and attaches it to the return dict as `last_usage`. The LangGraph default reducer overwrites `state.last_usage` on each node — but the `node_end` event fires after the node's return dict is produced, so `run_graph()` can read `last_usage` directly from the event's `data` and write it to `run_steps.token_usage` before it gets overwritten. ReAct agent nodes aggregate `last_usage` across all iterations of the tool-use loop.
- **Router nodes** store the destination node name directly in `state.current_route`. `add_conditional_edges` is called with a lambda that returns `state.current_route` as the destination directly (no route map intermediate). When `current_route == "__end__"` the lambda returns LangGraph's `END` sentinel.
- **`_resolve_path`** walks a dot-path string like `"context.classification.risk_level"` against the state dict — used by the router's `source` config and by `_resolve_templates` for mcp_tool argument interpolation like `{{input.affected_services}}`.

### `persistence.py` — `run_graph()` wrapper

Thin async generator around `stream_graph()`:

```python
async def run_graph(*, db, graph, graph_version_id, trigger_source, run_input, mcp_servers, agents, definition=None):
    # 1. Insert a runs row with status="running", started_at=now
    # 2. Yield {"event": "run_started", "data": {"run_id": "..."}}
    # 3. Iterate stream_graph(definition, mcp_servers, run_input, agents):
    #      - node_start → insert RunStep (status="running"), track in open_steps dict
    #      - node_end → close RunStep (status="succeeded"), write output_snapshot
    #                   + token_usage from last_usage, aggregate into run.token_usage
    #      - error → mark any still-open RunStep as failed, mark run as failed
    #      - done → break loop
    #      - Pass the event through verbatim to the caller
    # 4. finally: finalize runs row (status, completed_at, duration_ms, output_json, error_message)
```

Callers (the editor test endpoint and the public runs endpoint) both consume the same generator. Sync callers `async for event in run_graph(...)` and buffer to a JSON response; streaming callers wrap the generator in a `StreamingResponse`.

**The `run_started` event is emitted before the first stream event** so the frontend can correlate SSE output with a persisted run id.

### `mcp_client.py` — MCP protocol client

Thin wrapper around the official `mcp` Python SDK. Two transport functions: `list_tools(...)` and `call_tool(...)`, each with dispatch for `"http"` (via `sse_client`) or `"stdio"` (via `stdio_client` + `StdioServerParameters`). stdio servers spawn a fresh subprocess per call — simple and correct for demo; production deploys would want a session pool.

### `a2a/card.py` — A2A protocol client

Fetches `/.well-known/agent.json` and validates against an `AgentCard` Pydantic model. Also implements `send_message(agent_url, text)` — a minimal JSON-RPC 2.0 client that sends `message/send` and unpacks the agent's `parts` response. Used by the `a2a` node type in `runner.py`.

---

## Frontend structure

**React 19 + Vite + TanStack React Query + axios**. No Next.js, no SSR, no router library — pure state-based navigation.

### State-based navigation

`App.tsx` holds two pieces of top-level state:
- `view: "graphs" | "agents" | "mcp-servers" | "api-keys"` — which list page is showing
- `detailGraphId: string | null` / `editorGraphId: string | null` — overlay state for graph detail / editor

Rendering precedence: editor (if set) > detail (if set) > list view for `view`. Header tabs switch `view` but only render when neither detail nor editor is active.

### Component tree

```
<App>
 ├── <Header> (only when not in detail/editor)
 ├── List views (conditionally rendered on view):
 │   <GraphList>       <AgentList>       <MCPServerList>       <ApiKeyList>
 ├── <GraphDetail> (when detailGraphId set)
 │   ├── Header with back, slug, version badge, Edit, Publish buttons
 │   ├── Tab bar (6 tabs, all enabled through Plan C)
 │   └── Tab content:
 │       <OverviewTab>      summary cards, stats, node list
 │       <APIDocsTab>       Stripe-style reference generated from schemas
 │       <VersionsTab>      published version table
 │       <KeysTab>          filtered list of keys with scope over this graph
 │       <RunsTab>          paginated runs list + filters
 │         └── <RunDetailDrawer>  waterfall detail, input/output JSON, token usage
 │       <TestTab>          form-first test harness + live stream + examples
 │       <PublishModal>     confirmation with release notes
 │       <SchemasDrawer>    input/output schema editor (opened from GraphEditor toolbar)
 ├── <GraphEditor> (when editorGraphId set)
 │   ├── React Flow canvas
 │   ├── Node palette sidebar
 │   ├── Properties panel (node-type-specific editors)
 │   ├── Edge properties panel (condition editor)
 │   └── Schemas toolbar button → opens SchemasDrawer
 ├── Shared primitives:
 │   <Modal>              fixed-position overlay with lock-during-mutation support
 │   <Drawer>             right-side slide-over
 │   <UsageWarning>       usage list for delete confirmations
 │   <JsonSchemaEditor>   visual + JSON mode schema editor (readOnly supported)
 │   <SchemaFormGenerator> generates a form from a JSON schema (used by TestTab)
 └── Modals:
     <AgentFormModal>, <AgentDetailsDrawer>   from AgentList
     <MCPServerFormModal>, <MCPServerDetailsDrawer>  from MCPServerList
     <ApiKeyFormModal>, <RevealKeyModal>      from ApiKeyList
```

### API client

`frontend/src/api/client.ts` exports a flat list of typed async functions — one per endpoint. TanStack React Query handles caching and invalidation. Common query keys:
- `["graphs"]` — list
- `["graph", graphId]` — single
- `["graph-versions", graphId]`
- `["graph-runs", graphId, statusFilter]`
- `["run", runId]`
- `["agents"]`, `["mcp-servers"]`, `["api-keys"]`

When a mutation changes server state, its `onSuccess` invalidates the relevant keys so dependent queries refetch.

The `streamRun(graphId, input, onEvent, onDone, onError)` function is special — it doesn't use axios, it opens a `fetch()` directly to get a ReadableStream and parses SSE lines line-by-line. Returns an `AbortController` for cancellation.

### Types

`frontend/src/types/index.ts` holds the full TypeScript type surface — every entity has an interface, every Create/Update body has an interface. Types are manually kept in sync with backend Pydantic schemas; there is no codegen.

---

## Security model

### Authentication

**Management API (`/api/v1/*`)**: stubbed. The app hardcodes `DEV_ORG_ID` and `DEV_USER_ID` in every handler where a request would normally carry user context. To replace with real auth, add a FastAPI dependency that extracts the user from a session cookie or JWT and returns `(user_id, org_id)`; then replace every use of `DEV_USER_ID` / `DEV_ORG_ID` with the dependency value. The models are already carrying `created_by` and `org_id` so no migration is needed.

**Public API (`/v1/*`)**: `authenticate_api_key` dependency at `backend/app/security/auth.py`. Flow:
1. Extract `Authorization: Bearer <token>` from the request header
2. Validate it starts with `ap_live_`
3. `split_prefix(token)` → first 16 chars
4. `SELECT * FROM api_keys WHERE key_prefix = ?`
5. For each candidate: `bcrypt.checkpw(token.encode(), candidate.key_hash.encode())`
6. On match: reject 401 if `revoked_at` is set, else update `last_used_at`, return the `ApiKey` row
7. On miss after all candidates: 401

The handler then calls `check_graph_scope(api_key, graph_id)` after resolving the target graph. This raises 404 (not 403) for scope mismatches — deliberate, to avoid giving external callers a way to probe which graphs exist but they lack access to.

### Key storage

When a key is created:
1. `generate_plaintext_key()` returns `ap_live_ + secrets.token_urlsafe(24)` (→ ~40 chars total)
2. `hash_key(plaintext)` → bcrypt with a per-call salt
3. The database row stores `key_prefix`, `key_hash`, `key_last4` — never the full plaintext
4. The POST response (`ApiKeyCreatedOut`) includes the plaintext **exactly once**
5. The UI shows it in a `RevealKeyModal` with a copy button and a "You won't see this again" warning

This means:
- A database leak does NOT leak usable keys. An attacker with the DB dump still has to brute-force the bcrypt hashes, which is computationally infeasible at default bcrypt rounds.
- A GET request on `/api/v1/api-keys/{id}` will NEVER return the plaintext, because `ApiKeyOut` doesn't have a `key` field — only the subclass `ApiKeyCreatedOut` used by the create response does.

### Scope enforcement

An `api_key.scopes` value is either `["*"]` (wildcard) or a list of graph UUIDs as strings. `check_graph_scope(api_key, graph_id)`:
```python
if "*" in scopes: return
if str(graph_id) in scopes: return
raise HTTPException(status_code=404, detail="Graph not found")
```

Note that the comparison stringifies the graph ID. This matches how scopes are stored (strings) and how the public endpoint receives the graph (looked up by slug, then `.id` is a UUID object).

### JSON Schema validation

On public endpoints, the request body's `input` field is validated against `graph.input_schema` (or the pinned version's schema) via `jsonschema.Draft202012Validator`. On first error, a `SchemaValidationError` is raised with a field path like `/user/name: 'name' is a required property`. The handler catches and returns 422 with the error in the `{"error": ...}` field.

If the graph has no `input_schema` (nullable), validation is a no-op — the call goes through. This keeps legacy schemaless graphs working.

---

## Design decisions and gotchas

### Things that will trip you up

**1. The runner uses the raw Anthropic SDK, not LangChain `ChatAnthropic`.**

Consequence: LangGraph's `on_chat_model_stream` events never fire. If you expect per-token streaming to the frontend, you need to either switch to `ChatAnthropic` or manually stream the Anthropic response and synthesize `token` events yourself. The current token streaming in `stream_graph` is dead code from a previous iteration — it handles `on_chat_model_stream` but that event never arrives.

**2. Node IDs in React Flow must equal `node_key`, not the database UUID.**

`GraphEditor/index.tsx` has `toRFNodes(nodes)` that maps `n.node_key` to `id`. Edges reference `source` and `target` by `node_key` (strings like `"classify"`, `"route_risk"`). If you ever use the database UUID as the RF ID, edges won't connect because the edge rows use `source_node_key`/`target_node_key`.

**3. `graph.test_examples` is a jsonb list, not a table.**

It lives on the `graphs` row directly. Each example is `{id, name, input, output, created_at}` where `id` is a uuid **string** and `created_at` is an ISO datetime **string** (not a native uuid/datetime — jsonb can't hold those). The `POST /graphs/{id}/examples` endpoint append-rewrites the whole list; there's no child table.

**4. Router nodes store the destination, not the condition.**

When you write a router config:
```python
"routes": {"high": "assess_narrative", "medium": "fetch_deps", "low": "summarize"}
```
the router node's return dict is `{"current_route": "assess_narrative"}` (the destination), NOT `{"current_route": "high"}` (the matched key). `add_conditional_edges` is called with no `route_map`; the lambda returns `state["current_route"]` directly.

**5. Auth in the public endpoint returns 404 for scope mismatch.**

Do not "fix" this to 403 — it's intentional per the spec's security decision. 404 for both "graph missing" and "key lacks scope" prevents an attacker from enumerating graph existence.

**6. The test harness uses SAVEPOINT isolation.**

`backend/tests/conftest.py` constructs `AsyncSession(..., join_transaction_mode="create_savepoint")`. This means handlers can call `db.commit()` inside tests without breaking isolation — the savepoint is committed, but the outer connection-level transaction is rolled back in the fixture teardown. Without this, the tests in Tasks 5–8 would silently leak state between each other.

**7. `Base.metadata.create_all()` in tests does NOT run Alembic.**

The test fixture creates the schema from the current ORM models. Migration correctness is verified separately by `docker compose exec backend alembic upgrade head` hitting real Postgres on startup. If you add a model column without updating the relevant Alembic migration (or writing a new one), tests will pass but the real app will 500. The CI story for this is: run pytest + run migrations against a scratch database.

**8. Seed is idempotent by identity, not presence.**

`seed.py` uses fixed well-known UUIDs (`00000000-0000-0000-0000-000000000010`, etc.) and calls `_upsert_*` helpers that compare desired state to stored state. Running seed twice:
- If the desired state matches: no-op
- If the desired state changed in code (e.g. a new node added to the seed graph): updates the DB row in place

**Do NOT write seed logic that does "skip if any row exists" — that's what broke early iterations.**

**9. The migration chain is linear.**

```
f7d1bbf56602  initial
a2b3c4d5e6f7  a2a agent card + mcp tools_json
b3c4d5e6f7a8  graph versioning + schemas + slugs (Plan A)
c4d5e6f7a8b9  runs + run_steps (Plan B)
d5e6f7a8b9c0  api_keys (Plan C)
```

When you add a new migration, set its `down_revision` to the current head. Run `ls backend/alembic/versions/` to confirm.

**10. `frontend/src/api/client.ts` and backend router paths must agree on trailing slash.**

During Plan C implementation, there was a 307 redirect bug because the frontend called `/api-keys/` (trailing) and the router declared `@router.post("/")` → full path `/api-keys/` → matches. But the tests used `/api-keys` (no trailing) and FastAPI's default `redirect_slashes=True` would redirect them. The fix was to use `@router.post("")` (empty string) so the full path is `/api-keys` with no trailing slash. **Convention in this project: empty-string handler paths when there's no path param after the prefix.**

---

## Extension points

### Adding a new node type

Three files change:

1. **`backend/app/engine/runner.py`**: add a `_build_my_node(node_key, config)` function following the pattern of `_build_llm_node` / `_build_router_node`. It should return an `async def node(state: AgentState) -> dict` that produces a partial state update. Then add a new branch to the `if ntype == ...` cascade in `build_graph`.

2. **`frontend/src/components/GraphEditor/sidebar/NodePalette.tsx`**: add a new palette item with a `type` and a color.

3. **`frontend/src/components/GraphEditor/sidebar/PropertiesPanel.tsx`**: add a new conditional branch that renders form fields for the node type's `config_json`. Follow the pattern of the existing `llm` / `mcp_tool` / `a2a` branches.

If your new node type makes LLM calls, attach `last_usage` to its return dict like `_build_llm_node` does so it flows through `run_graph` → `run_steps.token_usage` automatically.

### Adding a new management endpoint

Pick the relevant router file in `backend/app/routers/` or create a new one. Follow the pattern:
1. Write a failing test in `backend/tests/test_your_feature.py` using the `client` and `db_session` fixtures from `conftest.py`.
2. Implement the endpoint.
3. Run `docker compose exec backend pytest tests/test_your_feature.py -v`.
4. If you created a new router file, register it in `backend/app/main.py`: `app.include_router(your_router, prefix="/api/v1")`.

### Adding a new migration

```bash
docker compose exec backend alembic revision --autogenerate -m "add_foo"
docker compose exec backend alembic upgrade head
```

Autogeneration compares the current ORM (in `backend/app/models/`) to the DB schema and emits a migration. Always review the generated file — it may miss index changes or Postgres-specific constraints. Batch mode (`with op.batch_alter_table(...)`) is required for constraint changes that need to work on SQLite (the test harness uses `create_all` so this doesn't matter for tests, but it matters if you want the migration to run against both Postgres and SQLite).

If your migration needs to backfill data, do it inline:
```python
op.execute("UPDATE foo SET bar = 'default' WHERE bar IS NULL")
```

### Adding a new frontend tab to GraphDetail

1. Create `frontend/src/components/GraphDetail/YourTab.tsx`.
2. Open `frontend/src/components/GraphDetail/index.tsx`, add an entry to the `TABS` array, import your component, add a conditional render in the content block.

For a new top-level nav tab (like "API Keys"):
1. Create a list component in `frontend/src/components/YourList/index.tsx`.
2. Update `App.tsx`: add the new value to the `View` type, import the component, render it in the view switch, add an entry to the Header tabs array.

---

## Testing strategy

**Backend**: pytest + pytest-asyncio + aiosqlite. The test fixture creates an in-memory SQLite database via `Base.metadata.create_all()` and gives each test a session with SAVEPOINT isolation. An ASGI transport client talks to the FastAPI app via `httpx.AsyncClient`, with the `get_db` dependency overridden to return the test's session.

TDD pattern followed in every backend test file:
```python
async def test_thing(client, db_session):
    # Set up fixture state via db_session.add(...)
    # Hit the endpoint via client.post(...)
    # Assert on the response body AND on db_session state
```

For tests that exercise the runner without hitting Anthropic, stub `stream_graph` via `monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)`. See `backend/tests/test_runs_persistence.py` for the pattern.

**Frontend**: no automated UI tests. Type-checking via `tsc --noEmit` is the only automation. Verification is manual through the browser.

---

## How to customize for your platform

If you're forking this as a starting point for a product:

### What to replace

1. **Stubbed auth** → your real auth system. Every handler currently uses `DEV_USER_ID` / `DEV_ORG_ID` from `backend/app/config.py`. Replace with a dependency that extracts user/org from a session cookie, JWT, or your SSO provider. Then grep for `DEV_USER_ID` and `DEV_ORG_ID` and replace each call site with the new dependency.
2. **Org slug resolution** → currently `orgs.slug` is set to `"demo"` by the seed. In a real multi-tenant deploy, you'd assign slugs at org creation time and enforce `(org_id, slug)` uniqueness for both orgs and graphs (already enforced in the migration).
3. **Demo seed** — `backend/app/seed.py` seeds one org, one user, one graph, one demo agent, one demo MCP server, and one demo API key with deterministic credentials. In production, disable the seed entirely (`DEBUG=false`) and let your admin create the initial data via the management API or a separate bootstrap process.
4. **Anthropic-only LLM provider** — the runner's LLM nodes hardcode `AsyncAnthropic(api_key=settings.anthropic_api_key)`. To support OpenAI / Bedrock / local models, abstract the provider behind a thin interface and route based on node config. The easiest path is a provider-per-node-config rather than a global swap.
5. **Mock seed A2A agent + mock MCP server** — they live in `backend/seed_services/` and exist in docker-compose only to make the demo graph runnable locally. You'd remove them in production.

### What to keep

- The **versioning model** (`graph_versions` + `@vN` pinning) is the hardest thing to retrofit and is worth keeping even if you change a lot around it.
- The **`run_graph()` wrapper pattern** — any persistence layer for graph execution is going to want something similar.
- The **prefix-lookup + bcrypt verify** API key pattern — it's GitHub / Stripe-standard and should fit most products.
- The **404 for scope mismatch** decision — it's genuinely important for security and worth preserving.
- The **spec-and-plan discipline** — it made this entire project tractable for an agent to execute with minimal backtracking.

### What to ignore

- `docs/superpowers/` is plugin-specific internal notes and specs from this build. You don't need it. Keep the README and this guide.
- The `.superpowers/` directory (gitignored) holds brainstorming session artifacts and isn't part of the app.

---

## What's next (Plan D)

The final phase. Spec section: `docs/superpowers/specs/2026-04-11-graph-as-api-design.md` §7.3 + §7.4.

- **`?mode=async`** — public run endpoint returns `{run_id, status: "queued"}` immediately. The run is inserted with `status="queued"` and a background worker pool claims it atomically (`UPDATE ... SET status='running' WHERE id=? AND status='queued'`).
- **Worker pool** — `backend/app/engine/jobs.py` (new) starts 3–5 threads that poll the runs table every second. Invoke `run_graph()` and fire webhook delivery on completion.
- **Webhook delivery** — optional `webhook_url` on async requests. On run completion, POST the payload to that URL with an `X-Agent-Platform-Signature: sha256=<hmac>` header signed with a per-key `webhook_secret`. Retry ladder: 30s → 2m → 10m → 1h → 6h, max 5 attempts.
- **New `webhook_deliveries` table** — one row per delivery attempt, linked to the run.
- **Cancel endpoint** — `POST /api/v1/runs/{run_id}/cancel` (queued and running async runs only; sync/stream are non-cancelable).
- **Orphan recovery** — on backend startup, flip any `running` run that's been in that state for >10 min to `failed` with a "worker restarted" error message.
- **UI** — new "Webhook deliveries" section in the `RunDetailDrawer`; async mode toggle in the `TestTab`.

Plan D is self-contained — it layers on top of what's on main without modifying the existing surface.

---

## Reference: file map

### Backend

```
backend/
  Dockerfile                     python:3.12-slim with requirements.txt
  requirements.txt               pinned versions; bcrypt, jsonschema, anthropic, langgraph, mcp
  alembic.ini                    Alembic config (DATABASE_URL read from env)
  pytest.ini                     asyncio_mode = auto; tests dir
  alembic/
    env.py                       async Alembic env; reads DATABASE_URL from os.environ
    versions/                    migration chain (5 files through Plan C)
  app/
    __init__.py
    main.py                      FastAPI app, lifespan, middleware, router registration, error handlers
    config.py                    Pydantic BaseSettings: DATABASE_URL, ANTHROPIC_API_KEY, CORS_ORIGINS, etc.
                                 Also exports DEV_ORG_ID and DEV_USER_ID constants
    db.py                        AsyncEngine, AsyncSessionLocal, Base (DeclarativeBase), get_db dep
    logging_config.py            JSON log formatter, request_id contextvar, configure_logging()
    models/
      __init__.py
      user.py                    Org, User
      agent.py                   Agent (A2A + LLM)
      mcp_server.py              MCPServer (http + stdio)
      graph.py                   Graph, GraphNode, GraphEdge, GraphVersion
      run.py                     Run, RunStep
      api_key.py                 ApiKey
    schemas/
      __init__.py
      execution.py               RunRequest
      graph.py                   GraphBase, GraphCreate, GraphOut, GraphSummary, GraphVersionSummary,
                                 GraphVersionOut, GraphPublishBody, GraphUpdate, GraphNodeSchema,
                                 GraphEdgeSchema
      agent.py                   AgentBase, AgentCreate, AgentUpdate, AgentOut
      mcp_server.py              MCPServerBase, MCPServerCreate, MCPServerUpdate, MCPServerOut
      run.py                     RunStepOut, RunSummary, RunOut, ExampleCreate, ExampleOut
      api_key.py                 ApiKeyCreate, ApiKeyOut, ApiKeyCreatedOut
    routers/
      __init__.py
      graphs.py                  /api/v1/graphs/ CRUD + publish + versions + PATCH
      execution.py               /api/v1/graphs/{id}/run — editor test SSE with run persistence
      runs.py                    /api/v1/graphs/{id}/runs list, /api/v1/runs/{id} detail, examples
      agents.py                  /api/v1/agents registry
      mcp_servers.py             /api/v1/mcp-servers registry
      api_keys.py                /api/v1/api-keys management
      public_runs.py             /v1/run/{org}/{slug} public endpoint (sync + stream)
    engine/
      __init__.py
      runner.py                  LangGraph StateGraph builder, node implementations, streaming events
      persistence.py             run_graph() wrapper — runs/run_steps persistence + usage aggregation
      mcp_client.py              MCP client for http/sse and stdio transports
    a2a/
      __init__.py
      card.py                    AgentCard model, fetch_agent_card, send_message (JSON-RPC)
    security/
      __init__.py
      auth.py                    authenticate_api_key dependency + check_graph_scope helper
    services/
      __init__.py
      publishing.py              validate_publishable() — publish pre-flight
      api_keys.py                generate_plaintext_key, split_prefix, hash_key, verify_key
      schema_validation.py       validate_against_schema() — jsonschema wrapper
    seed.py                      Idempotent dev seed for org/user/mcp/agent/graph/version/api_key
  seed_services/
    Dockerfile                   python:3.12-slim for the seed-agent container
    mock_a2a_agent.py            FastAPI app on port 8001 with /.well-known/agent.json + JSON-RPC
    mock_mcp_server.py           Stdio MCP server with lookup_dependencies tool
  tests/
    __init__.py
    conftest.py                  Session-scoped engine, SAVEPOINT db_session fixture, ASGI client
    test_smoke.py                Health + empty list checks
    test_publish_validation.py   Unit tests for publish validator
    test_publish.py              /graphs/{id}/publish integration tests
    test_versions.py             /graphs/{id}/versions tests
    test_patch_graph.py          PATCH graph tests
    test_list_graphs.py          GraphSummary.latest_version_number population tests
    test_runs_persistence.py     run_graph() wrapper tests
    test_execution_persistence.py  /graphs/{id}/run persistence tests
    test_runs_api.py             Runs list and detail endpoint tests
    test_examples.py             /graphs/{id}/examples tests
    test_api_key_service.py      generate/hash/verify service tests
    test_api_keys_api.py         /api/v1/api-keys management endpoint tests
    test_schema_validation.py    jsonschema wrapper tests
    test_public_runs_auth.py     Auth dependency tests on public endpoints
    test_public_runs_execution.py  Public endpoint execution tests (sync/stream/pinning/validation)
```

### Frontend

```
frontend/
  Dockerfile                     node:20 with npm install + vite --host 0.0.0.0
  package.json                   React 19, TypeScript, Vite, @xyflow/react, TanStack React Query
  tsconfig.json                  strict, module ESNext, JSX preserve, allowArbitraryExtensions
  vite.config.ts                 Vite config with proxy to backend
  index.html                     Vite entrypoint
  src/
    main.tsx                     Root render
    App.tsx                      Top-level state + header + routing
    api/client.ts                Axios client + typed functions + SSE streamRun helper
    types/index.ts               Every entity + Create/Update types + RunEvent union
    constants/models.ts          ANTHROPIC_MODELS list, DEFAULT_MODEL_ID
    vite-env.d.ts                Module declarations for CSS side-effect imports
    components/
      GraphList/index.tsx        Graph browsing + create + delete
      GraphDetail/
        index.tsx                Shell with header, tabs, publish modal
        OverviewTab.tsx
        APIDocsTab.tsx
        VersionsTab.tsx
        KeysTab.tsx
        RunsTab.tsx
        RunDetailDrawer.tsx
        TestTab.tsx
        PublishModal.tsx
      GraphEditor/
        index.tsx                React Flow canvas + sidebar + toolbar
        SchemasDrawer.tsx        Toolbar button → schemas drawer with Input/Output tabs
        nodes/index.tsx          Custom React Flow node renderers
        sidebar/
          NodePalette.tsx        Drag source
          PropertiesPanel.tsx    Per-node-type config form (LLM, router, mcp_tool, a2a, agent)
          EdgePropertiesPanel.tsx  Edge label/condition editor
      AgentList/
        index.tsx
        AgentFormModal.tsx
        AgentDetailsDrawer.tsx
      MCPServerList/
        index.tsx
        MCPServerFormModal.tsx
        MCPServerDetailsDrawer.tsx
      ApiKeyList/
        index.tsx
        ApiKeyFormModal.tsx
        RevealKeyModal.tsx
      RunPanel/index.tsx         Legacy in-editor run panel (still used; predates TestTab)
      shared/
        Modal.tsx                Centered fixed-position overlay
        Drawer.tsx               Right-side slide-over
        UsageWarning.tsx         Graph-usage list for delete confirmations
        JsonSchemaEditor.tsx     Visual + JSON schema editor (readOnly supported)
        SchemaFormGenerator.tsx  Form from a JSON schema (used by TestTab)
```

### Infrastructure

```
docker-compose.yml              Orchestrates 4 services: postgres, backend, frontend, seed-agent
.env.example                    Template for required ANTHROPIC_API_KEY + optional POSTGRES_PASSWORD
.gitignore                      .venv, .env, node_modules, __pycache__, data, .superpowers, .claude
```

### Documentation

```
README.md                             Root — quick start + feature overview
docs/INTEGRATION.md                   This file
docs/superpowers/specs/
  2026-04-11-graph-as-api-design.md   The architectural spec covering all four plans
docs/superpowers/plans/
  2026-04-11-plan-a-versioning-foundation.md
  2026-04-11-plan-b-runs-and-tabs.md
  2026-04-11-plan-c-api-keys-public-endpoints.md
```

---

## Appendix: the five-node demo graph

The seed creates a graph called "Change Request Risk Analyzer" that exercises every node type and feature. It's a useful reference for building your own graphs:

```
__start__
   ▼
[classify]                            LLM node
   │                                  - model: claude-sonnet-4-6
   │                                  - tool_use for structured output
   │                                  - writes context.classification = {risk_level, confidence, reasoning, key_concerns}
   ▼
[route_risk]                          Router node
   │                                  - source: context.classification.risk_level
   │                                  - routes: high → assess_narrative
   │                                            medium → fetch_deps
   │                                            low → summarize
   │                                  - default: summarize
   │
   ├─ "high" ────▶ [assess_narrative]     A2A node
   │                 │                     - agent_id: seed a2a agent
   │                 │                     - calls http://seed-agent:8001 via message/send
   │                 │                     - writes context.narrative = assessment text
   │                 ▼
   │              [fetch_deps]         MCP tool node
   │                 │                  - mcp_server_id: seed stdio server
   │                 │                  - tool_name: lookup_dependencies
   │                 │                  - arguments: {service_name: {{input.affected_services}}}
   │                 │                  - writes context.dependencies = [...]
   │                 ▼
   │              [summarize]          LLM node
   │                                    - include_context: true
   │                                    - system_prompt says "generate a markdown risk report"
   │                                    - produces final report as message_text
   │                                    ▼
   │                                 __end__
   │
   ├─ "medium" ──▶ [fetch_deps] ───▶ [summarize] ──▶ __end__
   │
   └─ "low" ────▶ [summarize] ──▶ __end__
```

Input schema (on the graph row):
```json
{
  "type": "object",
  "required": ["title", "description", "affected_services"],
  "properties": {
    "title":              {"type": "string"},
    "description":        {"type": "string"},
    "affected_services":  {"type": "array", "items": {"type": "string"}},
    "proposed_window":    {"type": "string"}
  }
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "classification": {
      "type": "object",
      "properties": {
        "risk_level":  {"type": "string", "enum": ["high", "medium", "low"]},
        "confidence":  {"type": "number"},
        "reasoning":   {"type": "string"},
        "key_concerns":{"type": "array", "items": {"type": "string"}}
      }
    },
    "report": {"type": "string", "description": "Final markdown risk report"}
  }
}
```

Try it:
```bash
curl -X POST "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{
    "title": "Upgrade payments-service to Python 3.12",
    "description": "Dependency bump and runtime upgrade. Staging validated.",
    "affected_services": ["payments-service", "ledger-service"],
    "proposed_window": "Saturday 02:00 UTC"
  }}' | jq
```

You'll get back a `{run_id, status: "succeeded", output: {...}}` response. Then open the Runs tab in the UI and click the new row to see the full waterfall — classify (LLM call), route_risk (decision), assess_narrative (A2A call to the seed agent), fetch_deps (stdio MCP call to the mock server), summarize (LLM consolidation). Each step shows timing, tokens used, and the output snapshot it produced.

---

*End of integration guide. Questions, gaps, or errors? Fix them directly and commit — this guide is the single best tool future-you has.*
