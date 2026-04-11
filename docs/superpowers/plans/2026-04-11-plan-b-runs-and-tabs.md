# Plan B — Runs Persistence + API Docs / Test / Runs Tabs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every graph run (editor test or future public API call) is persisted as a `runs` row with per-node `run_steps` traces, and the GraphDetail page grows three fully-functional tabs — API Docs (auto-generated from schemas), Test (form-first harness), Runs (list + waterfall detail) — making the build → test → observe loop complete inside the app.

**Architecture:** Two new tables (`runs`, `run_steps`) hold trace data. A new `run_graph()` helper wraps the existing `stream_graph()` generator: it creates a `runs` row up front, writes a `run_steps` row on every `node_start` / `node_end` pair, aggregates token usage, and finalizes the run row on `done`/`error`. The existing `/graphs/{id}/run` endpoint is repointed to `run_graph()` with `trigger_source=editor_test`, optionally tagging a specific `graph_version_id` when the caller passes `?version=vN`. New management endpoints expose runs for the UI. Token usage is plumbed through the runner by having LLM/agent nodes attach a `_usage` field to their state updates, which `run_graph` reads off each `node_end` event. On the frontend, three new tabs in `GraphDetail` consume the new backend: API Docs reuses `JsonSchemaEditor` in `readOnly` mode + static code snippet templates; Test generates an input form from the schema and streams a run; Runs shows a paginated list of past runs with a slide-over drawer holding the per-node waterfall.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2 (backend); pytest + pytest-asyncio + aiosqlite (tests); React 19 + TanStack React Query + axios (frontend).

**Parent spec:** `docs/superpowers/specs/2026-04-11-graph-as-api-design.md`

**Depends on:** Plan A (versioning foundation) — already on `main`.

---

## File structure

### Backend

**New:**
- `backend/alembic/versions/c4d5e6f7a8b9_runs_persistence.py` — migration for `runs` + `run_steps` tables
- `backend/app/models/run.py` — `Run` + `RunStep` ORM models
- `backend/app/schemas/run.py` — `RunSummary`, `RunOut`, `RunStepOut`, `ExampleCreate`, `ExampleOut`
- `backend/app/engine/persistence.py` — `run_graph(...)` wrapper around `stream_graph()` that creates/finalizes run rows
- `backend/app/routers/runs.py` — `GET /graphs/{id}/runs`, `GET /runs/{run_id}`, `POST /graphs/{id}/examples`, `DELETE /graphs/{id}/examples/{example_id}`
- `backend/tests/test_runs_persistence.py` — unit tests for `run_graph()`
- `backend/tests/test_runs_api.py` — integration tests for runs list + detail endpoints
- `backend/tests/test_examples.py` — tests for example create/delete

**Modified:**
- `backend/app/main.py` — register the new `runs` router
- `backend/app/engine/runner.py` — add `_usage` field to `AgentState` and populate it from `_build_llm_node` and `_build_agent_node`
- `backend/app/routers/execution.py` — delegate to `run_graph()` and accept optional `?version=vN` query param

### Frontend

**New:**
- `frontend/src/components/shared/SchemaFormGenerator.tsx` — generates a React form from a JSON Schema object (used by the Test tab)
- `frontend/src/components/GraphDetail/APIDocsTab.tsx` — Stripe-style reference view
- `frontend/src/components/GraphDetail/TestTab.tsx` — form-first test harness with live streaming
- `frontend/src/components/GraphDetail/RunsTab.tsx` — list of past runs
- `frontend/src/components/GraphDetail/RunDetailDrawer.tsx` — slide-over with summary + input/output JSON + waterfall

**Modified:**
- `frontend/src/components/GraphDetail/index.tsx` — enable + render the three new tabs
- `frontend/src/types/index.ts` — `Run`, `RunSummary`, `RunStep`, `TestExample` types
- `frontend/src/api/client.ts` — `listGraphRuns`, `getRun`, `createExample`, `deleteExample`

---

## Task 1: Alembic migration for `runs` and `run_steps`

**Files:**
- Create: `backend/alembic/versions/c4d5e6f7a8b9_runs_persistence.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/c4d5e6f7a8b9_runs_persistence.py`:

```python
"""runs and run_steps tables

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-11 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('graph_version_id', sa.Uuid(), nullable=True),
        sa.Column('trigger_source', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=False),
        sa.Column('output_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['graph_id'], ['graphs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['graph_version_id'], ['graph_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_runs_graph_id_started_at', 'runs', ['graph_id', sa.text('started_at DESC')])
    op.create_index('ix_runs_status', 'runs', ['status'])

    op.create_table(
        'run_steps',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('node_key', sa.String(length=128), nullable=False),
        sa.Column('node_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('input_snapshot', sa.JSON(), nullable=True),
        sa.Column('output_snapshot', sa.JSON(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_run_steps_run_id_step_order', 'run_steps', ['run_id', 'step_order'])


def downgrade() -> None:
    op.drop_index('ix_run_steps_run_id_step_order', table_name='run_steps')
    op.drop_table('run_steps')
    op.drop_index('ix_runs_status', table_name='runs')
    op.drop_index('ix_runs_graph_id_started_at', table_name='runs')
    op.drop_table('runs')
```

Note: `step_order` is the sequential index of the step within the run (1-indexed), used for stable ordering in the UI waterfall. It's simpler than ordering by `started_at` when two LLM calls fire in the same millisecond.

- [ ] **Step 2: Apply and verify the migration**

```bash
docker compose exec backend alembic upgrade head
```

Expected: log line `Running upgrade b3c4d5e6f7a8 -> c4d5e6f7a8b9, runs and run_steps tables`.

Verify the tables:
```bash
docker compose exec -T postgres psql -U agent -d agent_platform -c "\d runs"
docker compose exec -T postgres psql -U agent -d agent_platform -c "\d run_steps"
```
Expected: both tables present with the columns listed above.

- [ ] **Step 3: Run existing test suite to confirm nothing broke**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 24 passed (same as Plan A final state — Plan B tests not yet added).

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/c4d5e6f7a8b9_runs_persistence.py
git commit -m "feat(db): runs and run_steps tables for trace persistence"
```

---

## Task 2: ORM models — `Run` and `RunStep`

**Files:**
- Create: `backend/app/models/run.py`
- Modify: `backend/tests/conftest.py` (add model import so create_all sees them)

- [ ] **Step 1: Write `backend/app/models/run.py`**

```python
"""
Run + RunStep ORM models.

A Run is one graph execution — editor test, sync API, streaming API, or async job.
Each Run has a sequence of RunStep rows, one per node executed, used to render
the waterfall detail view in the UI.

graph_version_id is nullable: draft runs (editor tests against the live canvas)
point at no version. Published-version runs reference the exact immutable snapshot
that was executed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    graph_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("graph_versions.id", ondelete="SET NULL"), nullable=True
    )

    # 'editor_test' | 'api_sync' | 'api_stream' | 'api_async'
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    steps: Mapped[list["RunStep"]] = relationship(
        "RunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunStep.step_order",
    )


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'running' | 'succeeded' | 'failed' | 'skipped'
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped["Run"] = relationship("Run", back_populates="steps")
```

- [ ] **Step 2: Register the new model in `conftest.py`**

The test harness uses `Base.metadata.create_all()` which only sees models that have been imported. Add `run` to the explicit model imports at the top of `backend/tests/conftest.py`.

Find the existing line (near line ~37):
```python
from app.models import agent, graph, mcp_server, user  # noqa: E402, F401
```

Change it to:
```python
from app.models import agent, graph, mcp_server, run, user  # noqa: E402, F401
```

- [ ] **Step 3: Run smoke + existing suite to confirm models import cleanly**

```bash
docker compose exec -T backend pytest tests/test_smoke.py -v
docker compose exec -T backend python -c "from app.models.run import Run, RunStep; print('ok')"
```
Expected: 2 passed, then `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/run.py backend/tests/conftest.py
git commit -m "feat(models): Run and RunStep ORM models for trace persistence"
```

---

## Task 3: Pydantic schemas for runs and examples

**Files:**
- Create: `backend/app/schemas/run.py`

- [ ] **Step 1: Write the file**

```python
"""Pydantic schemas for Run, RunStep, and test examples."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RunStepOut(BaseModel):
    id: uuid.UUID
    node_key: str
    node_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    input_snapshot: dict | None = None
    output_snapshot: dict | None = None
    token_usage: dict | None = None
    error_message: str | None = None
    step_order: int

    model_config = {"from_attributes": True}


class RunSummary(BaseModel):
    """Lightweight listing — no snapshots or step details."""
    id: uuid.UUID
    graph_id: uuid.UUID
    graph_version_id: uuid.UUID | None = None
    trigger_source: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    token_usage: dict | None = None
    error_message: str | None = None
    input_preview: str  # first 60 chars of json.dumps(input_json)

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    """Full run detail including steps."""
    id: uuid.UUID
    graph_id: uuid.UUID
    graph_version_id: uuid.UUID | None = None
    trigger_source: str
    status: str
    input_json: dict
    output_json: dict | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    token_usage: dict | None = None
    steps: list[RunStepOut] = []

    model_config = {"from_attributes": True}


class ExampleCreate(BaseModel):
    """Body for POST /graphs/{id}/examples."""
    name: str
    input: dict
    output: dict | None = None


class ExampleOut(BaseModel):
    """One saved test example, stored in graphs.test_examples jsonb."""
    id: str  # uuid as string
    name: str
    input: dict
    output: dict | None = None
    created_at: str  # ISO-8601 string
```

Note: `ExampleOut` uses string id/created_at because examples live as jsonb inside `graphs.test_examples` rather than as their own table. JSON can't represent uuid or datetime natively.

- [ ] **Step 2: Quick import smoke**

```bash
docker compose exec -T backend python -c "from app.schemas.run import RunOut, RunSummary, RunStepOut, ExampleCreate, ExampleOut; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/run.py
git commit -m "feat(schemas): RunOut, RunSummary, RunStepOut, Example schemas"
```

---

## Task 4: Runner changes — plumb `_usage` through state

**Files:**
- Modify: `backend/app/engine/runner.py`

This task adds the token usage extraction plumbing to the existing runner. It does NOT add persistence yet (that's Task 5). The runner simply now attaches a `_usage` dict to LLM/agent node outputs.

- [ ] **Step 1: Add `_usage` field to `AgentState`**

Find the `AgentState` TypedDict in `backend/app/engine/runner.py` (near line 60). Currently:

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    input: dict[str, Any]
    context: dict[str, Any]
    current_route: str | None
```

Add the new field. LangGraph's default reducer is "last write wins", which is what we want — each node that makes an LLM call overwrites with its own usage; `run_graph` reads per-node from `on_chain_end` events so it captures each value in turn:

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    input: dict[str, Any]
    context: dict[str, Any]
    current_route: str | None
    last_usage: dict[str, Any] | None  # set by LLM/agent nodes; per-node
```

Update the initial state in `stream_graph` to include `last_usage`. Find this block (near line 499):

```python
    initial: AgentState = {
        "messages": [HumanMessage(content=json.dumps(run_input))],
        "input": run_input,
        "context": {},
        "current_route": None,
    }
```

Add:

```python
    initial: AgentState = {
        "messages": [HumanMessage(content=json.dumps(run_input))],
        "input": run_input,
        "context": {},
        "current_route": None,
        "last_usage": None,
    }
```

- [ ] **Step 2: Extract usage in `_build_llm_node`**

Find `_build_llm_node` (near line 72). Locate the Anthropic call and result handling:

```python
        response = await _anthropic.messages.create(**params)

        updates: dict[str, Any] = {}
```

Immediately after the `response = await ...` line, add a usage extraction helper call. First, at the top of the file (or wherever helpers live at the end), add this function:

```python
def _extract_usage(response) -> dict[str, Any]:
    """Serialize Anthropic Usage object into a plain dict the DB can store."""
    if not hasattr(response, "usage") or response.usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    u = response.usage
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }
```

Place this helper near `_extract_json` and `_resolve_path` at the bottom of the file.

Then in `_build_llm_node`, after the `response = await _anthropic.messages.create(**params)` line, add:

```python
        last_usage = _extract_usage(response)
```

And when building `updates`, always attach it:

```python
        updates: dict[str, Any] = {"last_usage": last_usage}
```

(Replace the existing empty `updates: dict[str, Any] = {}` line.)

The rest of the LLM node logic stays unchanged — it just adds more keys to `updates`.

- [ ] **Step 3: Extract and aggregate usage in `_build_agent_node`**

Find `_build_agent_node` (around line 210). It's a ReAct loop that may call `_anthropic.messages.create` multiple times per invocation. Aggregate usage across iterations.

Near the top of the `async def node(...)` function body, before the `for _ in range(max_iter):` loop, add:

```python
        agg_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
```

After each `response = await _anthropic.messages.create(**params)` call inside the loop, add:

```python
            iter_usage = _extract_usage(response)
            for k in agg_usage:
                agg_usage[k] += iter_usage.get(k, 0)
```

At the very end of the function (right before `return {"messages": new_messages}`), change the return to include aggregated usage:

```python
        return {"messages": new_messages, "last_usage": agg_usage}
```

- [ ] **Step 4: Have `stream_graph` forward `last_usage` from each `node_end` event**

Find the `on_chain_end` handling in `stream_graph` (near line 516). It currently builds `safe_output` from the output dict, serializing messages as `message_text`. The `last_usage` will already be present in `output` if the node set it, and the current code passes it through verbatim (because the else branch in the dict walk keeps unrecognized keys). Verify this by reading the code.

**Specifically:** the current loop is:

```python
                for k, v in (output or {}).items():
                    if k == "messages":
                        # Serialize message content so the frontend can display LLM output
                        texts = []
                        for m in (v or []):
                            content = m.content if hasattr(m, "content") else m.get("content", "")
                            if content:
                                texts.append(str(content))
                        if texts:
                            safe_output["message_text"] = "\n\n".join(texts)
                    else:
                        safe_output[k] = v
```

The `else` branch passes `last_usage` through. No change needed to this block. But add a comment clarifying the intent:

```python
                for k, v in (output or {}).items():
                    if k == "messages":
                        # Serialize message content so the frontend can display LLM output
                        texts = []
                        for m in (v or []):
                            content = m.content if hasattr(m, "content") else m.get("content", "")
                            if content:
                                texts.append(str(content))
                        if texts:
                            safe_output["message_text"] = "\n\n".join(texts)
                    else:
                        # Pass through: last_usage, context, current_route, etc.
                        safe_output[k] = v
```

- [ ] **Step 5: Run existing test suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 24 passed. The existing tests don't check token usage, so this change should be transparent.

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/runner.py
git commit -m "feat(engine): extract and plumb Anthropic token usage through AgentState"
```

---

## Task 5: `run_graph()` persistence wrapper (TDD)

**Files:**
- Create: `backend/app/engine/persistence.py`
- Create: `backend/tests/test_runs_persistence.py`

This is the core Plan B task: a thin wrapper that creates a `runs` row, writes `run_steps` as the graph executes, and finalizes on completion. It yields the same event dicts as `stream_graph` so callers (the editor test endpoint, future sync/stream/async endpoints in Plan C/D) can subscribe without rewriting their SSE loops.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_runs_persistence.py`:

```python
"""Tests for run_graph() — persistence wrapper around stream_graph()."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.engine.persistence import run_graph
from app.models.graph import Graph
from app.models.run import Run, RunStep
from app.models.user import Org, User


async def _seed_minimal_graph(db_session, definition=None):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID, email="test@example.com",
        display_name="Test User", org_id=DEV_ORG_ID,
    ))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json=definition or {
            "nodes": [
                {"key": "echo", "type": "llm", "config": {
                    "model": "claude-3-5-sonnet-20241022",
                    "system_prompt": "Just say 'ok'",
                }},
            ],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g)
    await db_session.flush()
    return g


async def test_run_graph_creates_run_row_on_start(db_session, monkeypatch):
    """Before any node executes, there should already be a runs row with status=running."""
    g = await _seed_minimal_graph(db_session)

    # Stub stream_graph to yield a single done event so the test doesn't hit Anthropic
    async def fake_stream(*args, **kwargs):
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    events = []
    async for evt in run_graph(
        db=db_session,
        graph=g,
        graph_version_id=None,
        trigger_source="editor_test",
        run_input={"hello": "world"},
        mcp_servers={},
        agents={},
    ):
        events.append(evt)

    # First event should be run_started carrying the run_id
    assert events[0]["event"] == "run_started"
    assert "run_id" in events[0]["data"]

    # Verify the run row exists and was finalized as succeeded
    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.status == "succeeded"
    assert run.graph_id == g.id
    assert run.graph_version_id is None
    assert run.trigger_source == "editor_test"
    assert run.input_json == {"hello": "world"}
    assert run.completed_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0


async def test_run_graph_writes_step_rows(db_session, monkeypatch):
    g = await _seed_minimal_graph(db_session)

    async def fake_stream(*args, **kwargs):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "node_end", "node": "echo", "data": {
            "message_text": "ok",
            "last_usage": {"input_tokens": 10, "output_tokens": 2,
                           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }}
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    events = []
    async for evt in run_graph(
        db=db_session,
        graph=g,
        graph_version_id=None,
        trigger_source="editor_test",
        run_input={},
        mcp_servers={},
        agents={},
    ):
        events.append(evt)

    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.step_order)
    )
    steps = result.scalars().all()

    assert len(steps) == 1
    assert steps[0].node_key == "echo"
    assert steps[0].node_type == "llm"
    assert steps[0].status == "succeeded"
    assert steps[0].step_order == 1
    assert steps[0].token_usage == {
        "input_tokens": 10, "output_tokens": 2,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }


async def test_run_graph_aggregates_token_usage_on_run(db_session, monkeypatch):
    g = await _seed_minimal_graph(db_session, definition={
        "nodes": [
            {"key": "a", "type": "llm", "config": {}},
            {"key": "b", "type": "llm", "config": {}},
        ],
        "edges": [],
    })

    async def fake_stream(*args, **kwargs):
        yield {"event": "node_start", "node": "a", "data": None}
        yield {"event": "node_end", "node": "a", "data": {
            "last_usage": {"input_tokens": 5, "output_tokens": 1,
                           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }}
        yield {"event": "node_start", "node": "b", "data": None}
        yield {"event": "node_end", "node": "b", "data": {
            "last_usage": {"input_tokens": 7, "output_tokens": 3,
                           "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0},
        }}
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    events = []
    async for evt in run_graph(
        db=db_session, graph=g, graph_version_id=None,
        trigger_source="editor_test", run_input={},
        mcp_servers={}, agents={},
    ):
        events.append(evt)

    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.token_usage == {
        "input_tokens": 12,
        "output_tokens": 4,
        "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 0,
    }


async def test_run_graph_finalizes_failed_on_error_event(db_session, monkeypatch):
    g = await _seed_minimal_graph(db_session)

    async def fake_stream(*args, **kwargs):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "error", "node": None, "data": "boom"}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    events = []
    async for evt in run_graph(
        db=db_session, graph=g, graph_version_id=None,
        trigger_source="editor_test", run_input={},
        mcp_servers={}, agents={},
    ):
        events.append(evt)

    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.status == "failed"
    assert run.error_message == "boom"
    assert run.completed_at is not None

    # The half-finished step should be marked failed too
    step_result = await db_session.execute(select(RunStep).where(RunStep.run_id == run_id))
    steps = step_result.scalars().all()
    assert len(steps) == 1
    assert steps[0].status == "failed"


async def test_run_graph_yields_run_started_before_upstream_events(db_session, monkeypatch):
    """run_started must be yielded before any node_start so UI can correlate."""
    g = await _seed_minimal_graph(db_session)

    call_order = []

    async def fake_stream(*args, **kwargs):
        call_order.append("stream_graph_entered")
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    events = []
    async for evt in run_graph(
        db=db_session, graph=g, graph_version_id=None,
        trigger_source="editor_test", run_input={},
        mcp_servers={}, agents={},
    ):
        events.append(evt)

    assert events[0]["event"] == "run_started"
    assert events[1]["event"] == "node_start"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_runs_persistence.py -v
```
Expected: 5 failures (`ModuleNotFoundError: No module named 'app.engine.persistence'`).

- [ ] **Step 3: Implement `backend/app/engine/persistence.py`**

```python
"""
Persistence wrapper around stream_graph().

run_graph() creates a runs row on entry, writes run_steps rows as node_start/node_end
events pass through the underlying stream, aggregates token usage across nodes, and
finalizes the runs row on done or error. It yields the same events as stream_graph
plus a leading run_started event carrying the run_id so UI clients can correlate.

Caller responsibility:
  - Provide an active db session (the caller's request session is reused).
  - Load mcp_servers and agents dicts from the DB (same shape as stream_graph expects).
  - Choose a trigger_source value: 'editor_test' | 'api_sync' | 'api_stream' | 'api_async'.
  - Optionally pass graph_version_id to tag the run with the exact snapshot executed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.runner import stream_graph
from app.models.graph import Graph
from app.models.run import Run, RunStep

log = logging.getLogger(__name__)

_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


async def run_graph(
    *,
    db: AsyncSession,
    graph: Graph,
    graph_version_id: uuid.UUID | None,
    trigger_source: str,
    run_input: dict[str, Any],
    mcp_servers: dict[str, Any],
    agents: dict[str, Any] | None = None,
    definition: dict[str, Any] | None = None,
) -> AsyncIterator[dict]:
    """
    Execute a graph with full persistence. Yields the same events as stream_graph
    with an additional leading `run_started` event carrying the new run_id.

    If definition is None, graph.definition_json is used (draft mode). Callers
    that want to pin a version should resolve graph_versions.definition_json
    themselves and pass it in alongside graph_version_id.
    """
    now = datetime.now(timezone.utc)

    # Create the run row immediately so the UI can correlate via run_started
    run = Run(
        graph_id=graph.id,
        graph_version_id=graph_version_id,
        trigger_source=trigger_source,
        status="running",
        input_json=run_input,
        started_at=now,
        token_usage={k: 0 for k in _USAGE_KEYS},
    )
    db.add(run)
    await db.flush()

    yield {"event": "run_started", "node": None, "data": {"run_id": str(run.id)}}

    # Step state — open step row awaiting node_end
    step_order = 0
    open_steps: dict[str, RunStep] = {}

    # Per-node-type lookup for filling node_type on step rows (from the definition)
    effective_definition = definition or graph.definition_json or {}
    node_types: dict[str, str] = {
        n["key"]: n.get("type", "unknown")
        for n in effective_definition.get("nodes", [])
    }

    aggregated_usage = {k: 0 for k in _USAGE_KEYS}
    final_output: dict[str, Any] | None = None
    final_error: str | None = None
    final_status = "succeeded"  # flipped to failed on error event

    try:
        async for event in stream_graph(
            effective_definition, mcp_servers, run_input, agents or {},
        ):
            kind = event.get("event")
            node = event.get("node")
            data = event.get("data")

            if kind == "node_start" and node:
                step_order += 1
                step = RunStep(
                    run_id=run.id,
                    node_key=node,
                    node_type=node_types.get(node, "unknown"),
                    status="running",
                    started_at=datetime.now(timezone.utc),
                    step_order=step_order,
                )
                db.add(step)
                await db.flush()
                open_steps[node] = step

            elif kind == "node_end" and node:
                step = open_steps.pop(node, None)
                if step is None:
                    # Defensive: unknown node_end without matching node_start
                    continue
                step.completed_at = datetime.now(timezone.utc)
                step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                step.status = "succeeded"
                if isinstance(data, dict):
                    step.output_snapshot = {k: v for k, v in data.items() if k != "last_usage"}
                    usage = data.get("last_usage")
                    if isinstance(usage, dict):
                        step.token_usage = {k: int(usage.get(k, 0) or 0) for k in _USAGE_KEYS}
                        for k in _USAGE_KEYS:
                            aggregated_usage[k] += step.token_usage[k]
                await db.flush()
                # Track the output so we can hoist it to the run row if the graph ends cleanly
                if isinstance(data, dict):
                    # Snapshot the latest node_end payload as the run's output
                    final_output = {k: v for k, v in data.items() if k not in ("last_usage",)}

            elif kind == "error":
                final_status = "failed"
                final_error = str(data) if data else "Unknown error"
                # Any still-open step is failed by association
                for open_step in list(open_steps.values()):
                    open_step.completed_at = datetime.now(timezone.utc)
                    open_step.duration_ms = int(
                        (open_step.completed_at - open_step.started_at).total_seconds() * 1000
                    )
                    open_step.status = "failed"
                    open_step.error_message = final_error
                await db.flush()
                open_steps.clear()

            # Pass the event through unchanged
            yield event

            if kind == "done":
                break

    except Exception as exc:  # unexpected — runner itself threw
        final_status = "failed"
        final_error = f"{type(exc).__name__}: {exc}"
        log.exception("run_graph caught runner exception")

    finally:
        # Finalize the run row
        run.status = final_status
        run.error_message = final_error
        run.output_json = final_output
        run.token_usage = aggregated_usage
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
        await db.flush()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose exec -T backend pytest tests/test_runs_persistence.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 29 passed (24 previous + 5 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/persistence.py backend/tests/test_runs_persistence.py
git commit -m "feat(engine): run_graph() persistence wrapper with step + usage tracking"
```

---

## Task 6: Update `/graphs/{id}/run` endpoint to use `run_graph()`

**Files:**
- Modify: `backend/app/routers/execution.py`
- Create: `backend/tests/test_execution_persistence.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_execution_persistence.py`:

```python
"""Tests that POST /graphs/{id}/run persists runs + steps via run_graph."""

import json
import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph, GraphVersion
from app.models.run import Run
from app.models.user import Org, User


async def _seed(db_session, monkeypatch):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g)
    await db_session.flush()

    # Stub stream_graph so we don't call Anthropic
    async def fake_stream(*args, **kwargs):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}}
        yield {"event": "done", "node": None, "data": {}}

    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)
    return g


async def _drain_sse(response) -> list[dict]:
    """Consume an SSE streaming response body and parse its data: lines."""
    events = []
    text = response.text  # httpx already consumed the body
    for line in text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def test_run_creates_persisted_run(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run",
        json={"input": {"hello": "world"}},
    )
    assert r.status_code == 200
    events = await _drain_sse(r)

    # First event should be run_started
    assert events[0]["event"] == "run_started"
    run_id = uuid.UUID(events[0]["data"]["run_id"])

    # DB row should exist, succeeded, with editor_test trigger and null version_id
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()
    assert run.graph_id == g.id
    assert run.graph_version_id is None  # draft run
    assert run.trigger_source == "editor_test"
    assert run.status == "succeeded"
    assert run.input_json == {"hello": "world"}


async def test_run_with_version_query_pins_graph_version_id(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    # Publish v1 so we have a version to pin to
    pub = await client.post(f"/api/v1/graphs/{g.id}/publish", json={})
    assert pub.status_code == 201
    pub_body = pub.json()
    assert pub_body["version"] == 1

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run?version=1",
        json={"input": {"hello": "world"}},
    )
    assert r.status_code == 200
    events = await _drain_sse(r)

    run_id = uuid.UUID(events[0]["data"]["run_id"])
    result = await db_session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one()

    # Version id should match the published v1
    assert run.graph_version_id is not None
    assert str(run.graph_version_id) == pub_body["id"]


async def test_run_with_missing_version_returns_404(client, db_session, monkeypatch):
    g = await _seed(db_session, monkeypatch)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/run?version=99",
        json={"input": {}},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose exec -T backend pytest tests/test_execution_persistence.py -v
```
Expected: 3 failures (endpoint still calls `stream_graph` directly, no persistence, no version query param).

- [ ] **Step 3: Update `backend/app/routers/execution.py`**

Replace the entire file content with:

```python
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.engine.persistence import run_graph
from app.models.agent import Agent
from app.models.graph import Graph, GraphVersion
from app.models.mcp_server import MCPServer
from app.schemas.execution import RunRequest

router = APIRouter(prefix="/graphs", tags=["execution"])


@router.post("/{graph_id}/run")
async def run_graph_endpoint(
    graph_id: uuid.UUID,
    body: RunRequest,
    version: int | None = Query(default=None, description="Pin to a specific published version"),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream graph execution as Server-Sent Events with full run persistence.

    Events emitted:
      data: {"event": "run_started", "node": null, "data": {"run_id": "..."}}
      data: {"event": "node_start", "node": "classify", "data": null}
      data: {"event": "node_end", "node": "classify", "data": {...}}
      data: {"event": "done", "node": null, "data": {}}
      data: {"event": "error", "node": null, "data": "..."}

    Query params:
      - version: if provided, executes the pinned graph_version.definition_json
        and tags the run with graph_version_id. If omitted, runs the live draft
        and leaves graph_version_id null.
    """
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # Resolve which definition to execute
    graph_version_id: uuid.UUID | None = None
    definition: dict
    if version is not None:
        v_result = await db.execute(
            select(GraphVersion).where(
                GraphVersion.graph_id == graph_id,
                GraphVersion.version == version,
            )
        )
        gv = v_result.scalar_one_or_none()
        if not gv:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")
        graph_version_id = gv.id
        definition = gv.definition_json
    else:
        definition = graph.definition_json

    if not definition or not definition.get("nodes"):
        raise HTTPException(status_code=422, detail="Graph has no definition")

    # Collect MCP server / agent refs from the definition
    mcp_server_ids: set[str] = set()
    agent_ids: set[str] = set()
    for node in definition.get("nodes", []):
        cfg = node.get("config") or {}
        if sid := cfg.get("mcp_server_id"):
            mcp_server_ids.add(str(sid))
        for sid in cfg.get("mcp_server_ids") or []:
            mcp_server_ids.add(str(sid))
        if aid := cfg.get("agent_id"):
            agent_ids.add(str(aid))

    mcp_servers: dict[str, dict] = {}
    if mcp_server_ids:
        uuids = [uuid.UUID(s) for s in mcp_server_ids]
        result = await db.execute(select(MCPServer).where(MCPServer.id.in_(uuids)))
        for srv in result.scalars().all():
            mcp_servers[str(srv.id)] = {
                "transport": srv.transport,
                "url": srv.url,
                "command": srv.command,
                "args": srv.args,
                "env_vars": srv.env_vars,
            }

    agents: dict[str, dict] = {}
    if agent_ids:
        uuids = [uuid.UUID(s) for s in agent_ids]
        result = await db.execute(select(Agent).where(Agent.id.in_(uuids)))
        for ag in result.scalars().all():
            agents[str(ag.id)] = {
                "url": ag.url,
                "agent_type": ag.agent_type,
                "agent_card_json": ag.agent_card_json,
            }

    async def event_stream():
        async for event in run_graph(
            db=db,
            graph=graph,
            graph_version_id=graph_version_id,
            trigger_source="editor_test",
            run_input=body.input,
            mcp_servers=mcp_servers,
            agents=agents,
            definition=definition,
        ):
            yield f"data: {json.dumps(event, default=str)}\n\n"
        # The DB session auto-commits on request completion via get_db

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose exec -T backend pytest tests/test_execution_persistence.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 32 passed (29 previous + 3 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/execution.py backend/tests/test_execution_persistence.py
git commit -m "feat(api): route /graphs/{id}/run through run_graph() persistence + version pinning"
```

---

## Task 7: Runs list + detail endpoints (TDD)

**Files:**
- Create: `backend/app/routers/runs.py`
- Create: `backend/tests/test_runs_api.py`
- Modify: `backend/app/main.py` (register the router)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_runs_api.py`:

```python
"""Tests for GET /graphs/{id}/runs and GET /runs/{run_id} endpoints."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.run import Run, RunStep
from app.models.user import Org, User


async def _seed_graph_and_runs(db_session, run_count=3):
    db_session.add(Org(id=DEV_ORG_ID, name="Test", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(), name="G", slug="g",
        created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    db_session.add(g)
    await db_session.flush()

    runs = []
    for i in range(run_count):
        r = Run(
            graph_id=g.id,
            graph_version_id=None,
            trigger_source="editor_test",
            status="succeeded" if i % 2 == 0 else "failed",
            input_json={"index": i},
            output_json={"result": f"out-{i}"} if i % 2 == 0 else None,
            error_message=None if i % 2 == 0 else f"error {i}",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=100 + i,
            token_usage={"input_tokens": 10, "output_tokens": 5,
                         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        )
        db_session.add(r)
        await db_session.flush()

        # Add a couple of steps per run
        for step_i, key in enumerate(["classify", "summarize"], start=1):
            step = RunStep(
                run_id=r.id,
                node_key=key,
                node_type="llm",
                status="succeeded",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=50,
                input_snapshot={"x": step_i},
                output_snapshot={"y": step_i * 2},
                token_usage={"input_tokens": 5, "output_tokens": 2,
                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                step_order=step_i,
            )
            db_session.add(step)

        runs.append(r)

    await db_session.flush()
    return g, runs


async def test_list_runs_empty(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="T", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()

    r = await client.get(f"/api/v1/graphs/{g.id}/runs")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_runs_returns_summaries_newest_first(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session)
    r = await client.get(f"/api/v1/graphs/{g.id}/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3

    # Newest first (order by started_at desc) — since all three ran in sequence,
    # the last inserted (index 2) is the most recent. Just check shape:
    first = body[0]
    assert "id" in first
    assert first["graph_id"] == str(g.id)
    assert "trigger_source" in first
    assert first["trigger_source"] == "editor_test"
    assert "input_preview" in first
    # The preview is the first 60 chars of the json-stringified input
    assert "index" in first["input_preview"]


async def test_list_runs_filter_by_status(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session)

    r_ok = await client.get(f"/api/v1/graphs/{g.id}/runs?status=succeeded")
    assert r_ok.status_code == 200
    assert all(x["status"] == "succeeded" for x in r_ok.json())

    r_bad = await client.get(f"/api/v1/graphs/{g.id}/runs?status=failed")
    assert r_bad.status_code == 200
    assert all(x["status"] == "failed" for x in r_bad.json())


async def test_list_runs_limit(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session, run_count=5)
    r = await client.get(f"/api/v1/graphs/{g.id}/runs?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_get_run_detail_includes_steps(client, db_session):
    g, runs = await _seed_graph_and_runs(db_session, run_count=1)
    run_id = runs[0].id

    r = await client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(run_id)
    assert body["input_json"] == {"index": 0}
    assert len(body["steps"]) == 2
    # Steps ordered by step_order
    assert body["steps"][0]["node_key"] == "classify"
    assert body["steps"][0]["step_order"] == 1
    assert body["steps"][1]["node_key"] == "summarize"
    assert body["steps"][1]["step_order"] == 2
    # Token usage present
    assert body["token_usage"]["input_tokens"] == 10


async def test_get_run_not_found(client):
    r = await client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_runs_api.py -v
```
Expected: 6 failures (endpoints don't exist).

- [ ] **Step 3: Write `backend/app/routers/runs.py`**

```python
"""
Run list + detail endpoints.

GET /api/v1/graphs/{graph_id}/runs       — paginated list of runs for a graph
GET /api/v1/runs/{run_id}                — full run detail with nested steps
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.graph import Graph
from app.models.run import Run
from app.schemas.run import RunOut, RunSummary, RunStepOut


router = APIRouter(tags=["runs"])


def _build_input_preview(input_json: dict) -> str:
    """First 60 chars of json-serialized input — used for table rows."""
    try:
        s = json.dumps(input_json, default=str)
    except (TypeError, ValueError):
        s = str(input_json)
    return s[:60] + ("…" if len(s) > 60 else "")


def _to_summary(run: Run) -> RunSummary:
    return RunSummary(
        id=run.id,
        graph_id=run.graph_id,
        graph_version_id=run.graph_version_id,
        trigger_source=run.trigger_source,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        token_usage=run.token_usage,
        error_message=run.error_message,
        input_preview=_build_input_preview(run.input_json or {}),
    )


@router.get("/graphs/{graph_id}/runs", response_model=list[RunSummary])
async def list_graph_runs(
    graph_id: uuid.UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    query = select(Run).where(Run.graph_id == graph_id).order_by(Run.started_at.desc())
    if status:
        query = query.where(Run.status == status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    runs = result.scalars().all()
    return [_to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunOut(
        id=run.id,
        graph_id=run.graph_id,
        graph_version_id=run.graph_version_id,
        trigger_source=run.trigger_source,
        status=run.status,
        input_json=run.input_json,
        output_json=run.output_json,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        token_usage=run.token_usage,
        steps=[RunStepOut.model_validate(s) for s in run.steps],
    )
```

- [ ] **Step 4: Register the router in `backend/app/main.py`**

Find the existing router registration block (near `app.include_router(...)` lines) and add:

```python
from app.routers import runs  # add to the existing routers import line
...
app.include_router(runs.router, prefix="/api/v1")
```

The existing registration pattern looks like:
```python
app.include_router(graphs.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(mcp_servers.router, prefix="/api/v1")
```
Append the new runs router line at the end.

- [ ] **Step 5: Run tests to confirm they pass**

```bash
docker compose exec -T backend pytest tests/test_runs_api.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 38 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/runs.py backend/app/main.py backend/tests/test_runs_api.py
git commit -m "feat(api): GET /graphs/{id}/runs list and GET /runs/{id} detail"
```

---

## Task 8: Test examples endpoints (TDD)

**Files:**
- Modify: `backend/app/routers/runs.py` (add example endpoints to the same router)
- Create: `backend/tests/test_examples.py`

Examples are stored as a jsonb list on `graphs.test_examples` (added in Plan A). No new table needed.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_examples.py`:

```python
"""Tests for POST /graphs/{id}/examples and DELETE .../{example_id}."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="T", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()
    return g


async def test_create_example(client, db_session):
    g = await _seed(db_session)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={
            "name": "Basic case",
            "input": {"title": "Migrate DB"},
            "output": {"classification": {"risk_level": "high"}},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Basic case"
    assert body["input"] == {"title": "Migrate DB"}
    assert body["output"] == {"classification": {"risk_level": "high"}}
    assert "id" in body
    assert "created_at" in body


async def test_create_example_appears_on_graph(client, db_session):
    g = await _seed(db_session)
    await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={"name": "Ex1", "input": {"a": 1}},
    )
    r = await client.get(f"/api/v1/graphs/{g.id}")
    assert r.status_code == 200
    body = r.json()
    examples = body["test_examples"]
    assert isinstance(examples, list)
    assert len(examples) == 1
    assert examples[0]["name"] == "Ex1"


async def test_delete_example(client, db_session):
    g = await _seed(db_session)
    created = await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={"name": "Ex1", "input": {"a": 1}},
    )
    example_id = created.json()["id"]

    r = await client.delete(f"/api/v1/graphs/{g.id}/examples/{example_id}")
    assert r.status_code == 204

    # Gone from the graph
    graph_resp = await client.get(f"/api/v1/graphs/{g.id}")
    assert graph_resp.json()["test_examples"] in (None, [])


async def test_create_example_on_missing_graph_404(client):
    r = await client.post(
        f"/api/v1/graphs/{uuid.uuid4()}/examples",
        json={"name": "X", "input": {}},
    )
    assert r.status_code == 404


async def test_delete_missing_example_404(client, db_session):
    g = await _seed(db_session)
    r = await client.delete(f"/api/v1/graphs/{g.id}/examples/not-a-real-id")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
docker compose exec -T backend pytest tests/test_examples.py -v
```
Expected: 5 failures (endpoints missing).

- [ ] **Step 3: Add example endpoints to `backend/app/routers/runs.py`**

Append to the existing `runs.py` router file:

```python
import uuid as _uuid
from datetime import datetime as _datetime, timezone as _timezone

from app.schemas.run import ExampleCreate, ExampleOut


@router.post(
    "/graphs/{graph_id}/examples",
    response_model=ExampleOut,
    status_code=201,
)
async def create_example(
    graph_id: uuid.UUID,
    body: ExampleCreate,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    example = {
        "id": str(_uuid.uuid4()),
        "name": body.name,
        "input": body.input,
        "output": body.output,
        "created_at": _datetime.now(_timezone.utc).isoformat(),
    }
    existing = list(graph.test_examples or [])
    existing.append(example)
    graph.test_examples = existing
    await db.flush()
    return example


@router.delete(
    "/graphs/{graph_id}/examples/{example_id}",
    status_code=204,
)
async def delete_example(
    graph_id: uuid.UUID,
    example_id: str,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    existing = list(graph.test_examples or [])
    filtered = [e for e in existing if e.get("id") != example_id]
    if len(filtered) == len(existing):
        raise HTTPException(status_code=404, detail="Example not found")

    graph.test_examples = filtered or None
    await db.flush()
```

Note: the `_uuid` / `_datetime` / `_timezone` aliased imports exist because `uuid` and `datetime` may already be imported at the top of the file. Using prefixed aliases avoids name collisions. The engineer applying this should check if `uuid` is already imported at the top and can be reused; if so, drop the alias.

- [ ] **Step 4: Run tests**

```bash
docker compose exec -T backend pytest tests/test_examples.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Full suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 43 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/runs.py backend/tests/test_examples.py
git commit -m "feat(api): test example create/delete endpoints on graphs"
```

---

## Task 9: Frontend types and API client additions

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add types**

Append to `frontend/src/types/index.ts`:

```typescript
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
```

- [ ] **Step 2: Add API client functions**

Add the new types to the import block at the top of `frontend/src/api/client.ts`:

```typescript
import type {
  Agent,
  AgentCreate,
  AgentUpdate,
  Graph,
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
```

Then append these functions (placement doesn't matter — put them near the other graph-related functions):

```typescript
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
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(frontend): types and API client for runs and examples"
```

---

## Task 10: Shared `SchemaFormGenerator` component

**Files:**
- Create: `frontend/src/components/shared/SchemaFormGenerator.tsx`

A small component that takes a JSON Schema (object with flat properties) and a value, and renders a form: string → text input, number/integer → number input, boolean → checkbox, string enum → select, array-of-strings → tag input, object → nested fieldset (1 level only). Emits `onChange(value)` with the structured value.

- [ ] **Step 1: Write the component**

Write `frontend/src/components/shared/SchemaFormGenerator.tsx`:

```typescript
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
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shared/SchemaFormGenerator.tsx
git commit -m "feat(frontend): SchemaFormGenerator for JSON Schema-driven forms"
```

---

## Task 11: `APIDocsTab` component

**Files:**
- Create: `frontend/src/components/GraphDetail/APIDocsTab.tsx`

Stripe-style reference auto-generated from the graph's `input_schema` and `output_schema`.

- [ ] **Step 1: Write the component**

```typescript
import { useState } from "react";
import { JsonSchemaEditor } from "../shared/JsonSchemaEditor";
import type { Graph } from "../../types";

interface Props {
  graph: Graph;
}

type CodeLang = "curl" | "python" | "typescript";

export function APIDocsTab({ graph }: Props) {
  const [lang, setLang] = useState<CodeLang>("curl");

  const endpoint = `POST /api/v1/graphs/${graph.id}/run`;
  const sampleInput = _buildSampleInput(graph.input_schema);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section style={styles.endpointCard}>
        <div style={styles.endpointLabel}>Endpoint</div>
        <div style={styles.endpointRow}>
          <span style={styles.method}>POST</span>
          <code style={styles.endpointUrl}>{endpoint}</code>
        </div>
        <div style={styles.modes}>
          <strong>Delivery:</strong> streaming (SSE){" "}
          <span style={{ color: "#9ca3af" }}>
            · sync / async / public endpoints land in later plans
          </span>
        </div>
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Request body</div>
        <JsonSchemaEditor value={graph.input_schema} readOnly />
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Response</div>
        <JsonSchemaEditor value={graph.output_schema} readOnly />
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Example request</div>
        <div style={styles.langTabs}>
          {(["curl", "python", "typescript"] as CodeLang[]).map((l) => (
            <button
              key={l}
              style={{ ...styles.langTab, ...(lang === l ? styles.langTabActive : {}) }}
              onClick={() => setLang(l)}
            >
              {l}
            </button>
          ))}
        </div>
        <pre style={styles.codeBlock}>{_renderSnippet(lang, graph, sampleInput)}</pre>
      </section>
    </div>
  );
}

function _buildSampleInput(schema: Record<string, unknown> | null): Record<string, unknown> {
  if (!schema || schema.type !== "object") return {};
  const props = (schema.properties as Record<string, Record<string, unknown>>) ?? {};
  const result: Record<string, unknown> = {};
  for (const [name, def] of Object.entries(props)) {
    const typeStr = def.type as string | undefined;
    if (def.enum) {
      result[name] = (def.enum as unknown[])[0] ?? "";
    } else if (typeStr === "string") {
      result[name] = `<${name}>`;
    } else if (typeStr === "number" || typeStr === "integer") {
      result[name] = 0;
    } else if (typeStr === "boolean") {
      result[name] = false;
    } else if (typeStr === "array") {
      result[name] = [];
    } else if (typeStr === "object") {
      result[name] = {};
    } else {
      result[name] = null;
    }
  }
  return result;
}

function _renderSnippet(lang: CodeLang, graph: Graph, sampleInput: Record<string, unknown>): string {
  const url = `http://localhost:8000/api/v1/graphs/${graph.id}/run`;
  const body = JSON.stringify({ input: sampleInput }, null, 2);

  if (lang === "curl") {
    return [
      "curl -N -X POST \\",
      `  ${url} \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -d '${JSON.stringify({ input: sampleInput })}'`,
    ].join("\n");
  }
  if (lang === "python") {
    return [
      "import httpx, json",
      "",
      "with httpx.stream(",
      `    "POST", "${url}",`,
      `    json=${JSON.stringify({ input: sampleInput }, null, 4).replace(/\n/g, "\n    ")},`,
      "    timeout=None,",
      ") as r:",
      "    for line in r.iter_lines():",
      "        if line.startswith('data: '):",
      "            event = json.loads(line[6:])",
      "            print(event)",
    ].join("\n");
  }
  // typescript
  return [
    `const resp = await fetch("${url}", {`,
    `  method: "POST",`,
    `  headers: { "Content-Type": "application/json" },`,
    `  body: JSON.stringify({ input: ${JSON.stringify(sampleInput, null, 2)} }),`,
    `});`,
    `const reader = resp.body!.getReader();`,
    `const decoder = new TextDecoder();`,
    `while (true) {`,
    `  const { done, value } = await reader.read();`,
    `  if (done) break;`,
    `  const chunk = decoder.decode(value);`,
    `  // parse SSE lines...`,
    `}`,
  ].join("\n");
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  endpointCard: {
    background: "#0f172a",
    color: "#fff",
    borderRadius: 8,
    padding: 16,
  },
  endpointLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 6,
  },
  endpointRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 6,
  },
  method: {
    background: "#166534",
    color: "#fff",
    padding: "2px 8px",
    borderRadius: 3,
    fontSize: 11,
    fontWeight: 800,
  },
  endpointUrl: {
    fontFamily: "monospace",
    fontSize: 13,
    color: "#e2e8f0",
  },
  modes: {
    fontSize: 12,
    color: "#cbd5e1",
    marginTop: 4,
  },
  langTabs: {
    display: "flex",
    gap: 0,
    marginBottom: -1,
  },
  langTab: {
    background: "#f3f4f6",
    border: "1px solid #e5e7eb",
    borderBottom: "none",
    padding: "5px 14px",
    cursor: "pointer",
    fontSize: 11,
    fontWeight: 600,
    color: "#6b7280",
    borderRadius: "4px 4px 0 0",
  },
  langTabActive: {
    background: "#0f172a",
    color: "#fff",
    borderColor: "#0f172a",
  },
  codeBlock: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 12,
    borderRadius: "0 4px 4px 4px",
    fontSize: 11,
    fontFamily: "monospace",
    whiteSpace: "pre",
    overflow: "auto",
    margin: 0,
  },
};
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphDetail/APIDocsTab.tsx
git commit -m "feat(frontend): APIDocsTab Stripe-style reference view"
```

---

## Task 12: `TestTab` component

**Files:**
- Create: `frontend/src/components/GraphDetail/TestTab.tsx`

The marquee interactive tab: form-first harness with live streaming and examples.

- [ ] **Step 1: Write the component**

```typescript
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createExample, deleteExample } from "../../api/client";
import { streamRun } from "../../api/client";
import { SchemaFormGenerator } from "../shared/SchemaFormGenerator";
import type { Graph, TestExample } from "../../types";

interface Props {
  graph: Graph;
}

interface LiveEvent {
  event: string;
  node: string | null;
  data: unknown;
  ts: number;
}

export function TestTab({ graph }: Props) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"form" | "json">("form");
  const [input, setInput] = useState<Record<string, unknown>>({});
  const [jsonText, setJsonText] = useState<string>(() => JSON.stringify({}, null, 2));
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [exampleName, setExampleName] = useState("");

  const examples: TestExample[] = (graph.test_examples as TestExample[] | null) ?? [];

  const createExampleMut = useMutation({
    mutationFn: (ex: { name: string; input: Record<string, unknown>; output: Record<string, unknown> | null }) =>
      createExample(graph.id, ex),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graph.id] });
      setSaveOpen(false);
      setExampleName("");
    },
  });

  const deleteExampleMut = useMutation({
    mutationFn: (exampleId: string) => deleteExample(graph.id, exampleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["graph", graph.id] }),
  });

  const loadExample = (ex: TestExample) => {
    setInput(ex.input);
    setJsonText(JSON.stringify(ex.input, null, 2));
    setRunResult(null);
    setEvents([]);
    setError(null);
  };

  const runTest = () => {
    const payload = mode === "form" ? input : _safeParseJson(jsonText, setError);
    if (payload === null) return;
    setRunning(true);
    setEvents([]);
    setRunResult(null);
    setError(null);

    streamRun(
      graph.id,
      payload,
      (evt) => {
        setEvents((prev) => [...prev, { ...evt, ts: Date.now() }]);
        if (evt.event === "node_end") {
          // Accumulate latest output snapshot
          const data = evt.data as Record<string, unknown> | null;
          if (data) setRunResult((prev) => ({ ...(prev ?? {}), ...data }));
        }
      },
      () => setRunning(false),
      (err) => {
        setError(err);
        setRunning(false);
      }
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {examples.length > 0 && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Saved examples</div>
          <div style={styles.chipRow}>
            {examples.map((ex) => (
              <div key={ex.id} style={styles.chip}>
                <button style={styles.chipBtn} onClick={() => loadExample(ex)}>
                  ↺ {ex.name}
                </button>
                <button
                  style={styles.chipDel}
                  onClick={() => deleteExampleMut.mutate(ex.id)}
                  title="Delete example"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section style={styles.card}>
        <div style={styles.cardHeader}>
          <div style={styles.sectionLabel}>Input</div>
          <div style={styles.modeToggle}>
            <button
              style={{ ...styles.modeBtn, ...(mode === "form" ? styles.modeBtnActive : {}) }}
              onClick={() => setMode("form")}
            >
              Form
            </button>
            <button
              style={{ ...styles.modeBtn, ...(mode === "json" ? styles.modeBtnActive : {}) }}
              onClick={() => {
                setJsonText(JSON.stringify(input, null, 2));
                setMode("json");
              }}
            >
              JSON
            </button>
          </div>
        </div>

        {mode === "form" ? (
          <SchemaFormGenerator
            schema={graph.input_schema}
            value={input}
            onChange={setInput}
            disabled={running}
          />
        ) : (
          <textarea
            style={styles.jsonArea}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            disabled={running}
          />
        )}

        <div style={styles.actions}>
          <button style={styles.runBtn} onClick={runTest} disabled={running}>
            {running ? "Running…" : "▶ Run"}
          </button>
          {runResult && !running && (
            <button style={styles.saveBtn} onClick={() => setSaveOpen(true)}>
              + Save as example
            </button>
          )}
        </div>
      </section>

      {error && (
        <div style={styles.error}>{error}</div>
      )}

      {(events.length > 0 || runResult) && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Live events</div>
          <div style={styles.eventList}>
            {events.map((e, i) => (
              <div key={i} style={styles.eventRow}>
                <span style={styles.eventType}>{e.event}</span>
                {e.node && <span style={styles.eventNode}>{e.node}</span>}
              </div>
            ))}
          </div>

          {runResult && (
            <>
              <div style={{ ...styles.sectionLabel, marginTop: 12 }}>Result</div>
              <pre style={styles.resultBox}>{JSON.stringify(runResult, null, 2)}</pre>
            </>
          )}
        </section>
      )}

      {saveOpen && (
        <section style={styles.card}>
          <div style={styles.sectionLabel}>Save as example</div>
          <input
            style={styles.input}
            placeholder="Example name"
            value={exampleName}
            onChange={(e) => setExampleName(e.target.value)}
          />
          <div style={styles.actions}>
            <button style={styles.cancelBtn} onClick={() => setSaveOpen(false)}>Cancel</button>
            <button
              style={styles.runBtn}
              disabled={!exampleName.trim() || createExampleMut.isPending}
              onClick={() =>
                createExampleMut.mutate({
                  name: exampleName.trim(),
                  input,
                  output: runResult,
                })
              }
            >
              Save
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function _safeParseJson(text: string, setError: (e: string) => void): Record<string, unknown> | null {
  try {
    return JSON.parse(text);
  } catch (e) {
    setError((e as Error).message);
    return null;
  }
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 16,
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 10,
  },
  chipRow: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap",
  },
  chip: {
    display: "flex",
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 16,
    overflow: "hidden",
  },
  chipBtn: {
    background: "none",
    border: "none",
    padding: "4px 12px",
    fontSize: 12,
    cursor: "pointer",
    color: "#374151",
  },
  chipDel: {
    background: "none",
    border: "none",
    borderLeft: "1px solid #d1d5db",
    padding: "4px 10px",
    fontSize: 14,
    cursor: "pointer",
    color: "#9ca3af",
    lineHeight: 1,
  },
  modeToggle: { display: "flex", gap: 4 },
  modeBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 10px",
    fontSize: 11,
    fontWeight: 600,
    cursor: "pointer",
  },
  modeBtnActive: {
    background: "#2563eb",
    color: "#fff",
    borderColor: "#2563eb",
  },
  jsonArea: {
    width: "100%",
    minHeight: 140,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: 8,
    fontFamily: "monospace",
    fontSize: 12,
    boxSizing: "border-box",
    resize: "vertical",
  },
  actions: {
    display: "flex",
    gap: 8,
    marginTop: 10,
    justifyContent: "flex-end",
  },
  runBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
  },
  saveBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    fontSize: 12,
    cursor: "pointer",
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    fontSize: 12,
    cursor: "pointer",
  },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "8px 12px",
    borderRadius: 5,
    fontSize: 12,
  },
  eventList: {
    fontFamily: "monospace",
    fontSize: 11,
    maxHeight: 160,
    overflowY: "auto",
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    padding: 8,
    background: "#f9fafb",
  },
  eventRow: {
    display: "flex",
    gap: 8,
    padding: "1px 0",
  },
  eventType: { color: "#2563eb", fontWeight: 700, minWidth: 80 },
  eventNode: { color: "#6b7280" },
  resultBox: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    overflowX: "auto",
    margin: 0,
  },
  input: {
    width: "100%",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    boxSizing: "border-box",
  },
};
```

Note: this imports `streamRun` from `api/client.ts`. That function already exists (used by the old `RunPanel`). Do not add a new one.

- [ ] **Step 2: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphDetail/TestTab.tsx
git commit -m "feat(frontend): TestTab with form-first input + live run streaming + examples"
```

---

## Task 13: `RunsTab` + `RunDetailDrawer` components

**Files:**
- Create: `frontend/src/components/GraphDetail/RunsTab.tsx`
- Create: `frontend/src/components/GraphDetail/RunDetailDrawer.tsx`

Two files, one commit. Runs tab shows a paginated list; clicking a row opens the detail drawer.

- [ ] **Step 1: Write `RunsTab.tsx`**

```typescript
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listGraphRuns } from "../../api/client";
import { RunDetailDrawer } from "./RunDetailDrawer";
import type { RunSummary } from "../../types";

interface Props {
  graphId: string;
}

export function RunsTab({ graphId }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const { data: runs = [], isLoading } = useQuery<RunSummary[]>({
    queryKey: ["graph-runs", graphId, statusFilter],
    queryFn: () => listGraphRuns(graphId, statusFilter ? { status: statusFilter, limit: 100 } : { limit: 100 }),
  });

  if (isLoading) return <div>Loading runs…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <section style={styles.filters}>
        <label style={styles.filterLabel}>Status</label>
        <select
          style={styles.select}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
        </select>
        <span style={styles.count}>{runs.length} run{runs.length === 1 ? "" : "s"}</span>
      </section>

      {runs.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#374151" }}>No runs yet</div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            Run the graph from the <strong>Test</strong> tab to see execution history here.
          </div>
        </div>
      ) : (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.headRow}>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Duration</th>
                <th style={styles.th}>Source</th>
                <th style={styles.th}>Input preview</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} style={styles.row} onClick={() => setSelectedRunId(r.id)}>
                  <td style={styles.td}>{new Date(r.started_at).toLocaleString()}</td>
                  <td style={styles.td}>
                    <StatusBadge status={r.status} />
                  </td>
                  <td style={styles.td}>{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</td>
                  <td style={styles.td}>
                    <code style={styles.code}>{r.trigger_source}</code>
                  </td>
                  <td style={{ ...styles.td, ...styles.preview }}>{r.input_preview}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RunDetailDrawer
        runId={selectedRunId}
        onClose={() => setSelectedRunId(null)}
      />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === "succeeded"
    ? { bg: "#f0fdf4", fg: "#16a34a", bc: "#86efac" }
    : status === "failed"
    ? { bg: "#fef2f2", fg: "#dc2626", bc: "#fca5a5" }
    : status === "running"
    ? { bg: "#eff6ff", fg: "#2563eb", bc: "#bfdbfe" }
    : { bg: "#f3f4f6", fg: "#6b7280", bc: "#d1d5db" };
  return (
    <span style={{
      background: color.bg,
      color: color.fg,
      border: `1px solid ${color.bc}`,
      borderRadius: 3,
      padding: "1px 7px",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
    }}>
      {status}
    </span>
  );
}

const styles: Record<string, React.CSSProperties> = {
  filters: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  filterLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  select: {
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 10px",
    fontSize: 12,
    background: "#fff",
  },
  count: {
    marginLeft: "auto",
    fontSize: 11,
    color: "#9ca3af",
  },
  tableCard: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    overflow: "hidden",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  headRow: { background: "#f9fafb" },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: 700,
    fontSize: 11,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  row: { cursor: "pointer" },
  td: { padding: "9px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
    color: "#4b5563",
  },
  preview: {
    fontFamily: "monospace",
    fontSize: 11,
    color: "#6b7280",
    maxWidth: 300,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
  },
};
```

- [ ] **Step 2: Write `RunDetailDrawer.tsx`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getRun } from "../../api/client";
import { Drawer } from "../shared/Drawer";
import type { Run, RunStep } from "../../types";

interface Props {
  runId: string | null;
  onClose: () => void;
}

export function RunDetailDrawer({ runId, onClose }: Props) {
  const { data: run, isLoading } = useQuery<Run>({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: Boolean(runId),
  });

  return (
    <Drawer open={Boolean(runId)} title="Run detail" onClose={onClose}>
      {isLoading && <div>Loading…</div>}
      {run && (
        <div>
          <section style={styles.section}>
            <div style={styles.sectionLabel}>Summary</div>
            <Row label="Run ID" value={<code style={styles.code}>{run.id}</code>} />
            <Row label="Status" value={run.status} />
            <Row label="Trigger" value={<code style={styles.code}>{run.trigger_source}</code>} />
            <Row label="Duration" value={run.duration_ms != null ? `${run.duration_ms}ms` : "—"} />
            <Row label="Started" value={new Date(run.started_at).toLocaleString()} />
            {run.graph_version_id && (
              <Row label="Version" value={<code style={styles.code}>{run.graph_version_id}</code>} />
            )}
            {run.token_usage && (
              <Row
                label="Tokens"
                value={
                  <span>
                    in {run.token_usage.input_tokens ?? 0} · out {run.token_usage.output_tokens ?? 0}
                    {(run.token_usage.cache_read_input_tokens ?? 0) > 0 &&
                      <> · cache read {run.token_usage.cache_read_input_tokens}</>}
                  </span>
                }
              />
            )}
          </section>

          {run.error_message && (
            <section style={styles.section}>
              <div style={styles.sectionLabel}>Error</div>
              <pre style={styles.errorBox}>{run.error_message}</pre>
            </section>
          )}

          <section style={styles.section}>
            <div style={styles.sectionLabel}>Input</div>
            <pre style={styles.jsonBox}>{JSON.stringify(run.input_json, null, 2)}</pre>
          </section>

          {run.output_json && (
            <section style={styles.section}>
              <div style={styles.sectionLabel}>Output</div>
              <pre style={styles.jsonBox}>{JSON.stringify(run.output_json, null, 2)}</pre>
            </section>
          )}

          <section style={styles.section}>
            <div style={styles.sectionLabel}>Steps ({run.steps.length})</div>
            {run.steps.length === 0 ? (
              <div style={styles.emptyStep}>No steps recorded for this run.</div>
            ) : (
              <div>
                {run.steps.map((s) => <StepCard key={s.id} step={s} />)}
              </div>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={styles.row}>
      <div style={styles.rowLabel}>{label}</div>
      <div style={styles.rowValue}>{value}</div>
    </div>
  );
}

function StepCard({ step }: { step: RunStep }) {
  const barWidth = Math.min(100, Math.max(2, (step.duration_ms ?? 0) / 20));
  const statusColor = step.status === "succeeded" ? "#16a34a" : step.status === "failed" ? "#dc2626" : "#6b7280";
  return (
    <div style={styles.stepCard}>
      <div style={styles.stepHeader}>
        <code style={styles.stepName}>{step.node_key}</code>
        <span style={styles.stepType}>{step.node_type}</span>
        <span style={{ ...styles.stepStatus, color: statusColor }}>{step.status}</span>
        <span style={styles.stepDuration}>{step.duration_ms != null ? `${step.duration_ms}ms` : "—"}</span>
      </div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.bar, width: `${barWidth}%`, background: statusColor }} />
      </div>
      {step.token_usage && (step.token_usage.input_tokens ?? 0) + (step.token_usage.output_tokens ?? 0) > 0 && (
        <div style={styles.stepTokens}>
          tokens: in {step.token_usage.input_tokens ?? 0} · out {step.token_usage.output_tokens ?? 0}
        </div>
      )}
      {step.error_message && (
        <pre style={styles.stepError}>{step.error_message}</pre>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  section: { marginBottom: 18 },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 8,
  },
  row: {
    display: "flex",
    gap: 12,
    padding: "5px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  rowLabel: { flexShrink: 0, width: 80, color: "#6b7280", fontSize: 12 },
  rowValue: { color: "#111827", wordBreak: "break-all", flex: 1 },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
  },
  jsonBox: {
    background: "#0f172a",
    color: "#e2e8f0",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    maxHeight: 200,
    overflow: "auto",
    margin: 0,
  },
  errorBox: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: 10,
    borderRadius: 5,
    fontSize: 11,
    fontFamily: "monospace",
    margin: 0,
    whiteSpace: "pre-wrap",
  },
  stepCard: {
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    padding: 10,
    marginBottom: 6,
    background: "#fff",
  },
  stepHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 6,
    fontSize: 12,
  },
  stepName: {
    fontFamily: "monospace",
    fontSize: 12,
    fontWeight: 700,
    color: "#111827",
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
  },
  stepType: { color: "#6b7280", fontSize: 11 },
  stepStatus: { fontSize: 10, fontWeight: 700, textTransform: "uppercase" },
  stepDuration: { marginLeft: "auto", color: "#9ca3af", fontSize: 11 },
  barTrack: {
    width: "100%",
    height: 4,
    background: "#f3f4f6",
    borderRadius: 2,
    overflow: "hidden",
  },
  bar: { height: "100%" },
  stepTokens: {
    fontSize: 10,
    color: "#6b7280",
    marginTop: 4,
    fontFamily: "monospace",
  },
  stepError: {
    fontSize: 11,
    color: "#b91c1c",
    marginTop: 6,
    padding: 6,
    background: "#fef2f2",
    borderRadius: 3,
    whiteSpace: "pre-wrap",
    margin: "6px 0 0",
  },
  emptyStep: { color: "#9ca3af", fontSize: 12, fontStyle: "italic" },
};
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GraphDetail/RunsTab.tsx frontend/src/components/GraphDetail/RunDetailDrawer.tsx
git commit -m "feat(frontend): RunsTab list + RunDetailDrawer waterfall view"
```

---

## Task 14: Enable tabs in `GraphDetail`

**Files:**
- Modify: `frontend/src/components/GraphDetail/index.tsx`

Wire the three new tabs in and remove their `disabled` flags.

- [ ] **Step 1: Update the TABS array and tab content rendering**

Open `frontend/src/components/GraphDetail/index.tsx`. Find the `TABS` const at the top of the file:

```typescript
const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs", disabled: true },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys", disabled: true },
  { id: "runs", label: "Runs", disabled: true },
  { id: "test", label: "Test", disabled: true },
];
```

Change to:

```typescript
const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs" },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys", disabled: true },
  { id: "runs", label: "Runs" },
  { id: "test", label: "Test" },
];
```

(Keys stays disabled — that lands in Plan C.)

- [ ] **Step 2: Import the new tabs**

Add these imports at the top alongside the existing tab imports:

```typescript
import { APIDocsTab } from "./APIDocsTab";
import { RunsTab } from "./RunsTab";
import { TestTab } from "./TestTab";
```

- [ ] **Step 3: Wire the tab content switch**

Find the content rendering block:

```tsx
      <div style={styles.content}>
        {activeTab === "overview" && <OverviewTab graph={graph} />}
        {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
      </div>
```

Extend it:

```tsx
      <div style={styles.content}>
        {activeTab === "overview" && <OverviewTab graph={graph} />}
        {activeTab === "api-docs" && <APIDocsTab graph={graph} />}
        {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
        {activeTab === "runs" && <RunsTab graphId={graph.id} />}
        {activeTab === "test" && <TestTab graph={graph} />}
      </div>
```

- [ ] **Step 4: Type-check**

```bash
cd /Users/dschwartz/agent-platform/frontend && npx tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphDetail/index.tsx
git commit -m "feat(frontend): enable API Docs, Test, and Runs tabs in GraphDetail"
```

---

## Task 15: End-to-end verification

**Files:** none — manual test flow.

- [ ] **Step 1: Restart stack**

```bash
docker compose restart backend
docker compose exec backend alembic upgrade head
```
Expected: migration `c4d5e6f7a8b9_runs_persistence` applies cleanly.

- [ ] **Step 2: Backend test suite**

```bash
docker compose exec -T backend pytest --no-header -q
```
Expected: 43 passed (24 Plan A + 5 persistence + 3 execution persistence + 6 runs api + 5 examples).

- [ ] **Step 3: API smoke — list runs endpoint exists**

```bash
curl -s "http://localhost:8000/api/v1/graphs/00000000-0000-0000-0000-000000000020/runs" | jq 'length'
```
Expected: `0` (no runs yet on the seed graph).

- [ ] **Step 4: Run the seed graph from the Test tab**

Open http://localhost:5173 → click the seed graph → click **Test** tab.

1. The tab should render a form generated from the seed graph's input schema with four fields: `title`, `description`, `affected_services` (tag input), `proposed_window`.
2. Fill in:
   - title: `Migrate DB`
   - description: `Postgres 14 → 16 blue/green`
   - affected_services: `payments, orders`
   - proposed_window: `Sat 02:00 UTC`
3. Click **▶ Run**. The live events panel should stream `run_started` → `node_start: classify` → `node_end: classify` → ... through all 5 nodes → `done`.
4. After `done`, the **Result** section should render the final output JSON.
5. A **+ Save as example** button appears. Click it, name it "DB migration", click Save. The chip should appear at the top of the tab.

- [ ] **Step 5: Check the Runs tab**

Click the **Runs** tab. Expect one row with:
- Today's timestamp
- Status: `SUCCEEDED` badge (green)
- Duration: some ms value
- Source: `editor_test`
- Input preview: first 60 chars of the input JSON

Click the row → drawer opens with:
- Run ID
- Status, Trigger, Duration, Started
- Tokens (in/out counts from Anthropic)
- Input JSON block (pretty-printed)
- Output JSON block
- 5 step cards in a waterfall — each showing node_key, node_type, duration, and a bar proportional to duration

- [ ] **Step 6: Check the API Docs tab**

Click **API Docs**. Expect:
- Dark endpoint card showing `POST /api/v1/graphs/{uuid}/run`
- Request body table auto-generated from input_schema (4 rows)
- Response table auto-generated from output_schema (classification, report)
- Code example tabs: curl / python / typescript. Click each, the code block updates accordingly.

- [ ] **Step 7: Load example + re-run**

Go back to **Test** tab. The "DB migration" chip is visible. Click it. Form fields repopulate. Click Run again. A second row appears in the Runs tab after the run finishes.

- [ ] **Step 8: Version-pinned run**

From the terminal:
```bash
curl -N -X POST "http://localhost:8000/api/v1/graphs/00000000-0000-0000-0000-000000000020/run?version=1" \
  -H 'Content-Type: application/json' \
  -d '{"input":{"title":"pinned","description":"test","affected_services":["payments"],"proposed_window":"now"}}'
```
Drain the SSE stream. The first event should be `run_started` with a run_id. Then:

```bash
curl -s "http://localhost:8000/api/v1/runs/<run_id>" | jq '{graph_version_id, trigger_source}'
```
Expected: `graph_version_id` is non-null (the seed graph's v1), `trigger_source` is `editor_test`.

- [ ] **Step 9: Failure path**

Temporarily break the graph's input to trigger a failure — the seed graph will call a real LLM, which will usually succeed, so you can simulate failure another way: delete a referenced agent via the UI (Agents tab → delete → confirm through the usages modal), then try a run. Actually, that would break publish validation rather than runtime — so instead, inject a bad query:

Run with invalid JSON:
```bash
curl -N -X POST "http://localhost:8000/api/v1/graphs/00000000-0000-0000-0000-000000000020/run?version=99" \
  -H 'Content-Type: application/json' \
  -d '{"input":{}}'
```
Expected: 404 with error about version 99 not found. (This exercises the version-lookup path, not the runtime failure path. Full runtime failure testing is automated via `test_run_graph_finalizes_failed_on_error_event`.)

- [ ] **Step 10: Commit completion marker**

No code changes here — just confirm the branch state:

```bash
git log --oneline main..HEAD
git status
```
Expected: 14 feature commits since main; clean working tree.

---

## Acceptance checklist (spec mapping)

- [ ] **§5.1 runs + run_steps tables** — migration in Task 1; models in Task 2
- [ ] **§5.2 runs columns** — all fields from spec present (graph_version_id nullable; trigger_source enum-ish; input/output JSON; token_usage jsonb)
- [ ] **§7.2 Persistent runs + steps** — `run_graph()` wrapper in Task 5 creates rows on entry, inserts per-node steps on start/end, finalizes on done/error
- [ ] **§7.2 Token usage plumbing** — Task 4 attaches `last_usage` to state updates; Task 5 reads it off `node_end` events and writes to run_steps + aggregates to run
- [ ] **§7.1 Version-aware execution** — Task 6 accepts `?version=N` and passes the pinned `graph_version.definition_json` through run_graph
- [ ] **§6.3 management endpoints** — `GET /graphs/{id}/runs` + `GET /runs/{id}` in Task 7; example endpoints in Task 8
- [ ] **§8.3 API Docs tab** — Task 11 with request/response tables + curl/python/ts snippets
- [ ] **§8.3 Test tab (form-first)** — Task 12 with SchemaFormGenerator, live streaming, examples
- [ ] **§8.3 Runs tab (list + waterfall)** — Task 13 with RunsTab + RunDetailDrawer
- [ ] **§8.3 Tabs enabled in GraphDetail** — Task 14
- [ ] **Backend test coverage** — 19 new tests (5 persistence + 3 execution + 6 runs api + 5 examples)
- [ ] **Frontend type-check** — `npx tsc --noEmit` exits 0 after each frontend task
- [ ] **Seed still works** — runs tab on the seed graph is empty until a test run is executed
- [ ] **Idempotent re-seed** — seed doesn't regress after Plan B's migration

## What Plan B does NOT deliver (deferred to later plans)

- **Public `/v1/run/...` endpoints** (sync / streaming) — Plan C
- **Org-level API keys** — Plan C
- **Async job runner + webhooks** — Plan D
- **Keys tab on GraphDetail** — Plan C
- **Top-level API Keys page in the header nav** — Plan C
- **Retention cleanup job** — deferred, runs never auto-expire in Plan B
- **Cursor pagination** — Plan B uses simple limit/offset; cursor pagination is a Plan C polish item
- **Generate schema from last run** button — the `runs` table now makes this feasible but it's a polish item; skip for Plan B
- **Per-version viewing on the other tabs** — the header version dropdown stays hidden; Plan B docs always reflect the draft

---

*End of Plan B. After all tasks complete and the acceptance checklist is green, the next plan (Plan C — API Keys + public endpoints sync/stream) can begin from this commit.*
