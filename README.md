# Agent Platform

A multi-tenant, Dify-style platform for building, versioning, testing, and publishing LangGraph-based agent workflows as public HTTP APIs. Teams work in **workspaces** whose membership is derived from their **Active Directory groups**, build graphs in a React Flow canvas, wire them to workspace-scoped registries of MCP servers and A2A agents, share registry entries through a **cross-workspace catalog**, and expose published workflows as authenticated REST/SSE endpoints.

Think: **GitHub Actions for AI agents, with AD-driven tenancy** — you design the workflow visually, publish a version, and consumers call it via HTTP with a bearer token; who can build what is governed entirely by AD group membership.

## What you can do with it

- **Work in AD-mapped workspaces** — tenancy is derived from the user's AD groups via group→(workspace, role) mappings. No invites; move people between AD groups and their access follows. Roles: viewer / editor / admin / owner. See `docs/MULTITENANCY.md`.
- **Build graph workflows visually** — drag nodes (LLM, router, MCP tool, A2A agent, ReAct agent) onto a canvas, wire edges, set structured JSON Schema for inputs/outputs.
- **Register external tools per workspace** — point the platform at A2A agents (HTTP, discovered via `/.well-known/agent.json`) and MCP servers (HTTP/SSE or stdio subprocess). Registries are tenant-isolated.
- **Share through the catalog** — workspace admins publish agents and MCP servers to a cross-workspace catalog; other workspaces browse and install their own copies (with lineage).
- **Test interactively** — form-first test harness generates an input form from your schema, streams execution events live, and saves runs for later inspection.
- **Version and publish** — `draft` / `v1` / `v2` / ... immutable snapshots. Consumers can pin or ride `latest`.
- **Observe every run** — per-node waterfall, token usage (Anthropic input/output/cache tokens), input/output JSON, error traces. 30-day retention.
- **Call as a public API** — `POST /v1/run/{workspace}/{graph-slug}` with an `ap_live_...` bearer token. Sync JSON, SSE streaming, or (Plan D) async webhook delivery.
- **Manage access** — per-workspace API keys scoped to specific graphs (or wildcard). Hashed at rest, shown once at creation, revokable.

## Tech stack

**Backend** — Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, LangGraph, Anthropic SDK (direct), MCP Python SDK, bcrypt, jsonschema, pytest + pytest-asyncio + aiosqlite.

**Frontend** — React 19, TypeScript, Vite, @xyflow/react (React Flow), TanStack React Query, axios.

**Infrastructure** — Docker Compose orchestrating Postgres 16 + backend + frontend + a mock seed A2A agent (separate container).

## Quickstart

```bash
cp .env.example .env    # fill in ANTHROPIC_API_KEY (and optionally POSTGRES_PASSWORD)
docker compose up --build
```

- **Frontend UI:** http://localhost:5173
- **Backend API + OpenAPI docs:** http://localhost:8000/docs
- **Postgres:** `localhost:5432` (user `agent`, db `agent_platform`, password from `.env`)
- **Seeded workspaces:** `Demo Workspace` (slug `demo`) and `ML Research` (slug `ml-research`), with AD group mappings `agent-platform-admins`→demo/owner, `agent-platform-users`→demo/editor, `ml-research-team`→ml-research/owner.
- **Dev identity:** without an SSO proxy, requests fall back to `dev@example.com` in groups `agent-platform-admins, agent-platform-users` (owner of Demo). Use *Settings → Identity (dev simulator)* in the UI to act as any user/groups.
- **Seeded demo graph:** `Change Request Risk Analyzer` — a 5-node workflow that classifies a change request, fetches service dependencies (via MCP), optionally calls an A2A risk-assessor agent for high-risk changes, and produces a markdown risk report.
- **Seeded catalog entries:** the demo MCP server and A2A agent are published to the cross-workspace catalog.
- **Seeded demo API key:** `ap_live_demoseedkey0000000000000000000000` (local dev only; `*` scope; safe to use in curl examples).

### Curl the demo

```bash
# Sync call against the seeded graph
curl -X POST "http://localhost:8000/v1/run/demo/change-risk-analyzer" \
  -H "Authorization: Bearer ap_live_demoseedkey0000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"input":{
    "title":"Migrate payments DB to Postgres 16",
    "description":"Zero-downtime blue/green migration",
    "affected_services":["payments-service"],
    "proposed_window":"Sat 02:00 UTC"
  }}'
```

### Dev loop

Source is volume-mounted into both backend and frontend containers. Changes hot-reload without rebuilding:

- **Backend** — uvicorn `--reload` watches `/app`; `.py` changes restart in ~1s. Alembic runs on every startup (idempotent) so schema changes from pulled migrations just work.
- **Frontend** — Vite HMR; `.tsx` changes update in the browser instantly.

Common one-off commands:

```bash
# Run the backend test suite (95 tests, ~25s)
docker compose exec backend pytest -v

# Type-check the frontend
docker compose exec frontend npx tsc --noEmit

# Create a new migration after editing a model
docker compose exec backend alembic revision --autogenerate -m "add_something"
docker compose exec backend alembic upgrade head

# Exec into containers
docker compose exec backend bash
docker compose exec frontend sh

# Inspect the Postgres state directly
docker compose exec postgres psql -U agent -d agent_platform
```

## Architecture at a glance

```
backend/
  app/
    main.py              FastAPI app, lifespan (runs migrations + seed), CORS, error handlers
    config.py            Pydantic BaseSettings (DATABASE_URL, ANTHROPIC_API_KEY, AUTH_*, ...)
    db.py                Async SQLAlchemy engine + Base + get_db dependency
    logging_config.py    Structured JSON logging with request_id
    models/              ORM: user, org (workspace), tenant_group_mapping, agent,
                              mcp_server, graph, graph_version, run, run_step, api_key
    schemas/             Pydantic models used in routers
    routers/             FastAPI routers (all /api/v1 routes are workspace-scoped)
      graphs.py            /api/v1/graphs — CRUD + publish + versions + PATCH
      execution.py         /api/v1/graphs/{id}/run — editor test runs (SSE)
      runs.py              /api/v1/graphs/{id}/runs, /api/v1/runs/{id}, examples
      agents.py            /api/v1/agents — agent registry + catalog publish
      mcp_servers.py       /api/v1/mcp-servers — MCP registry + catalog publish
      api_keys.py          /api/v1/api-keys — key management (admin)
      workspaces.py        /api/v1/me, /api/v1/workspaces, group-mapping admin
      catalog.py           /api/v1/catalog — cross-workspace browse + install
      public_runs.py       /v1/run/{org}/{slug} — authenticated public endpoint
    engine/
      runner.py            LangGraph StateGraph builder, node implementations,
                           astream_events consumer + token usage extraction
      persistence.py       run_graph() — wraps stream_graph with runs/run_steps
                           persistence and run_started event
      mcp_client.py        MCP client (HTTP/SSE + stdio) via mcp Python SDK
    a2a/
      card.py              A2A agent card fetch + JSON-RPC message/send client
    security/
      auth.py              authenticate_api_key dep + check_graph_scope
      identity.py          SSO-header identity, AD-group membership resolution,
                           WorkspaceContext dependency + require_role
    services/
      publishing.py        publish pre-flight validation (empty, dangling refs)
      api_keys.py          generate_plaintext_key, hash_key, verify_key
      schema_validation.py validate_against_schema (jsonschema wrapper)
    seed.py                Idempotent dev seed: org, user, MCP server, A2A agent,
                           5-node demo graph, auto-publish v1, demo API key

  seed_services/           Standalone services in docker-compose:
    mock_a2a_agent.py      FastAPI app on port 8001 — serves /.well-known/agent.json
                           and JSON-RPC message/send for the demo A2A agent
    mock_mcp_server.py     Stdio MCP server with lookup_dependencies tool
  alembic/                 Database migrations (4 total through Plan C)
  tests/                   pytest suite (80 tests through Plan C)

frontend/
  src/
    api/client.ts          Axios client with ~45 typed functions + SSE streamRun helper;
                           injects identity + X-Workspace-Id headers on every call
    identity.ts            Dev identity simulator + active-workspace persistence
    types/index.ts         Shared TypeScript interfaces for every resource
    constants/models.ts    Anthropic model list (shared by multiple UIs)
    App.tsx                Top-level shell: workspace switcher, header tabs
                           (Studio / Agents / Tools / Catalog / API Keys / Settings),
                           detail/editor state machine
    components/
      Catalog/               Cross-workspace catalog browse + install
      WorkspaceSettings/     Group-mapping admin, workspace creation, dev identity
      GraphList/             Browse and create graphs
      GraphDetail/           "Product page" for a graph — 6 tabs:
        index.tsx              Shell + header + tab bar + publish modal
        OverviewTab.tsx        Summary, stats, node list
        APIDocsTab.tsx         Stripe-style auto-generated reference
        VersionsTab.tsx        Published version history
        KeysTab.tsx            Filtered API keys with access to this graph
        RunsTab.tsx            Paginated run list
        RunDetailDrawer.tsx    Right-side waterfall detail
        TestTab.tsx            Form-first test harness with live streaming
        PublishModal.tsx       Publish confirmation with release notes
        SchemasDrawer.tsx      Input/output schema editor (in GraphEditor toolbar)
      GraphEditor/           React Flow canvas, node palette, properties panel
      AgentList/             Agents registry (list, create, details drawer, delete)
      MCPServerList/         MCP servers registry
      ApiKeyList/            API key management with show-once plaintext reveal
      shared/                Modal, Drawer, UsageWarning, JsonSchemaEditor,
                             SchemaFormGenerator
```

## How things are laid out by concept

| Concept | What it is | Where it lives |
|---|---|---|
| **Graph** | A directed workflow of nodes (LLM / router / mcp_tool / a2a / agent) | `models/graph.py` → `Graph`, `GraphNode`, `GraphEdge` |
| **Graph version** | Immutable snapshot of a graph's `definition_json` + schemas at publish time | `models/graph.py` → `GraphVersion` |
| **Run** | One execution of a graph (editor test, sync API, streaming API, or async) | `models/run.py` → `Run` |
| **Run step** | Per-node trace row — timing, input/output snapshot, token usage | `models/run.py` → `RunStep` |
| **Agent** | External reference to an A2A HTTP agent or a direct LLM agent | `models/agent.py` → `Agent` |
| **MCP server** | External reference to an HTTP/SSE or stdio MCP server | `models/mcp_server.py` → `MCPServer` |
| **API key** | Per-workspace bearer token, scoped to specific graphs or wildcard, hashed at rest | `models/api_key.py` → `ApiKey` |
| **Workspace** | The tenant boundary (legacy table name `orgs`); every resource carries `org_id` | `models/user.py` → `Org` |
| **Group mapping** | AD group → (workspace, role); the only membership mechanism | `models/user.py` → `TenantGroupMapping` |
| **User** | JIT-provisioned from SSO headers; `ad_groups` is an informational cache | `models/user.py` → `User` |
| **Catalog entry** | An agent/MCP server with `visibility='catalog'`, installable cross-workspace | `routers/catalog.py` |

## The delivered plans

Implementation was split into sequential plans. Plans A–C and the multi-tenancy phase are delivered; Plan D remains.

- **Plan A — Versioning foundation + Graph detail page** (merged). `graph_versions` table, publish workflow, input/output schemas, GraphDetail page replacing the old click-to-editor flow, shared JSON Schema editor.
- **Plan B — Runs persistence + API Docs / Test / Runs tabs** (merged). `runs` + `run_steps` tables, `run_graph()` persistence wrapper, token usage extraction, three new tabs on GraphDetail.
- **Plan C — API Keys + public endpoints** (merged). `api_keys` table with bcrypt, `authenticate_api_key` dependency, `POST /v1/run/{org}/{slug}` sync + stream modes, `@vN` version pinning, API Keys top-level page, show-once plaintext reveal.
- **Multi-tenancy + catalog** (this phase). AD-group-derived workspaces and roles, SSO-header identity with JIT provisioning, workspace-scoped registries, cross-workspace agent/MCP catalog with install lineage, workspace switcher + Settings + Catalog UI. See `docs/MULTITENANCY.md`.
- **Plan D — Async jobs + Webhooks** (planned). `?mode=async`, worker pool, HMAC-signed webhook delivery, retry ladder, cancel endpoint, webhook deliveries section in the run detail drawer.

The full **spec** is at `docs/superpowers/specs/2026-04-11-graph-as-api-design.md` — 500+ lines covering every architectural decision, data model field, endpoint contract, and non-goal.

## Documentation

- **`README.md`** (this file) — quick start + orientation
- **`docs/MULTITENANCY.md`** — AD-group tenancy model: identity headers, role derivation, catalog semantics, production checklist.
- **`docs/INTEGRATION.md`** — deep guide for another engineer (human or Claude instance) picking up the project or integrating into their own platform. Covers architecture, data model, API contracts, extension points, and customization patterns.
- **`docs/superpowers/specs/`** — architectural specs (one per feature)
- **`docs/superpowers/plans/`** — task-by-task implementation plans (one per phase)

## Key design decisions

- **Alembic migrations auto-run on startup** — idempotent, safe, no migration step in deploy workflow.
- **Structured JSON logging** — every log record includes `request_id` via `contextvars`; trace a single request through the whole stack by grep.
- **Consistent error schema** — `{"error": "...", "request_id": "..."}`; no stack traces leak to clients.
- **CORS configurable via env** — `CORS_ORIGINS=http://localhost:5173,https://prod.example.com` — never wildcard.
- **Seed is idempotent by identity** — rerunning `seed()` on a warm DB is a no-op, NOT "skip if graphs exist". Re-applies desired state to the seeded entities (well-known UUIDs) and leaves user-created rows alone.
- **API keys: prefix-lookup + bcrypt verify** — the first 16 chars are stored as an indexed `key_prefix`; the full key is bcrypt-hashed. Auth path: lookup by prefix, verify by hash. GitHub / Stripe pattern.
- **404 for scope mismatch, not 403** — the public `/v1/run/*` endpoints return 404 when the API key lacks access, identical to "graph not found". The same rule applies to cross-workspace access on the management API. Avoids enumeration oracles.
- **AD is the membership source of truth** — no invite/membership tables; `tenant_group_mappings` × the request's group headers decide access on every request. The backend trusts identity headers from the SSO proxy (`AUTH_DEV_FALLBACK=false` in production).
- **LangGraph `astream_events(version="v2")`** feeds SSE chunks to the browser; `run_graph()` wraps the stream with DB persistence.
- **Token usage plumbed via `AgentState.last_usage`** — LLM nodes attach `response.usage` to their state update; `run_graph` reads it from each `node_end` event and writes to `run_steps.token_usage` + aggregates to `runs.token_usage`.

## Development workflow

This project was built with specs-and-plans. If you're extending it:

1. **Spec a feature first** (if it's non-trivial): put it in `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`. Cover data model, API, UX, non-goals, risks.
2. **Write a plan**: `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` with task-by-task TDD steps.
3. **TDD for backend changes**: failing test → implement → passing test → commit. See any existing `backend/tests/test_*.py` for the pattern.
4. **Manual browser verification for frontend changes** — no automated UI tests in this repo.
5. **Type-check the frontend** after every frontend change: `docker compose exec frontend npx tsc --noEmit`.

## Contributing

See `docs/INTEGRATION.md` for the deep guide. Start by reading the design spec, then pick a task from a plan, then follow the TDD loop the existing tests already demonstrate.
