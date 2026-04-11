# Agent Platform

Platform for onboarding, managing, building, customizing, and deploying chat and agentic solutions across teams.

## Quickstart

```bash
cp .env.example .env    # fill in ANTHROPIC_API_KEY (and optionally POSTGRES_PASSWORD)
docker compose up --build
```

- Frontend: http://localhost:5173  
- Backend API + docs: http://localhost:8000/docs  
- Postgres: localhost:5432 (user: `agent`, db: `agent_platform`, password from `.env`)

The first `up` takes longer — Postgres initialises, Alembic runs the migration, then seed data is inserted. After that, `up` is fast (Alembic is idempotent, seed skips existing rows).

## Dev loop

Source is volume-mounted into both containers. Changes hot-reload without rebuilding:

- **Backend**: uvicorn `--reload` watches `/app` — save a `.py` file, it restarts in ~1s.
- **Frontend**: Vite HMR — save a `.tsx` file, it updates in the browser instantly.

To exec into a running container:
```bash
docker compose exec backend bash
docker compose exec frontend sh
```

To run a one-off command (e.g. generate a new migration after a schema change):
```bash
docker compose exec backend alembic revision --autogenerate -m "add_something"
docker compose exec backend alembic upgrade head
```

## Architecture

```
backend/
  app/
    models/       SQLAlchemy ORM (user, org, agent, mcp_server, graph + nodes/edges)
    schemas/      Pydantic request/response models
    routers/      FastAPI endpoints (graphs, agents, mcp_servers, execution)
    engine/
      runner.py       LangGraph StateGraph builder + astream_events streamer
      mcp_client.py   MCP client — HTTP/SSE and stdio transports via mcp SDK
  seed_mcp_server/    Bundled demo stdio MCP server (change risk analyzer)
  alembic/            Database migrations

frontend/
  src/
    api/            Typed API client + SSE stream helper
    components/
      GraphList/    Browse, create, clone, delete graphs
      GraphEditor/  React Flow canvas + node palette + properties panel + edge editor
      RunPanel/     JSON input + real-time SSE token stream
    types/          Shared TypeScript interfaces
```

## Database

**Default: Postgres** (via docker-compose).

The platform runs on Postgres in all environments — local dev included, via docker-compose. SQLite is supported by the ORM layer and still works for local scripting/testing, but is not the intended runtime.

### Switching to an external Postgres

1. Set `DATABASE_URL` in `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:pass@your-host:5432/agent_platform
   ```
2. Run migrations:
   ```bash
   docker compose exec backend alembic upgrade head
   ```

### Schema design notes

- All tables carry `created_by` (user_id) and `org_id` — present from day 1 so real auth is a drop-in when added (no migration needed).
- `graphs.definition_json` is a denormalized snapshot of nodes+edges used by the execution engine. `graph_nodes`/`graph_edges` rows are the normalized source of truth for the editor. Both are kept in sync on every save.
- `mcp_servers` and `agents` are **external references** — the platform invokes them but does not host them. Both stdio (subprocess) and HTTP/SSE MCP transports are supported.

## Key design decisions

- **Alembic migrations** — run automatically on startup (idempotent). Generate new migrations via `alembic revision --autogenerate`.
- **Structured logging** — JSON lines with `request_id` threaded through every log record.
- **Error responses** — consistent `{"error": ..., "request_id": ...}` schema; no stack traces.
- **CORS** — explicitly scoped to `cors_origins` setting, never wildcard. Configurable via `CORS_ORIGINS` env var (comma-separated).
- **Stubbed auth** — `DEV_USER_ID`/`DEV_ORG_ID` are hardcoded constants. Replace with request context when real auth lands.
- **LangGraph streaming** — `.astream_events()` feeds SSE chunks directly to the browser's `RunPanel`.
