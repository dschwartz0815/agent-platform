# Plan A — Versioning Foundation + Graph Detail Page Shell

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the versioning foundation, schema contracts, and graph detail page shell so teams can publish immutable versions of a graph and see the graph as a product (not just a canvas).

**Architecture:** A new `graph_versions` table stores immutable snapshots. The `graphs` table gains `slug`, `input_schema`, `output_schema`, `latest_published_version_id`, `retention_days`, `test_examples`. The `orgs` table gains `slug`. A new `POST /graphs/{id}/publish` endpoint freezes the draft into a new version row; `GET /graphs/{id}/versions` lists them. The frontend adds a new `GraphDetail` component that replaces the click-to-editor flow; the canvas editor is reached via an explicit **Edit** button inside `GraphDetail`. A new shared `JsonSchemaEditor` component is used both in a Schemas drawer (inside the editor) and as a read-only renderer (in later plans). Nothing in this plan is user-gated behind auth; everything still runs in the dev-org context.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest + pytest-asyncio + aiosqlite for tests, React 19, @xyflow/react, TanStack React Query, axios.

**Parent spec:** `docs/superpowers/specs/2026-04-11-graph-as-api-design.md`

---

## File structure

### Backend

**New:**
- `backend/tests/__init__.py`
- `backend/tests/conftest.py` — shared test fixtures (in-memory SQLite DB, ASGI client)
- `backend/tests/test_smoke.py` — sanity test
- `backend/tests/test_publish.py` — publish endpoint tests
- `backend/tests/test_versions.py` — versions list/detail tests
- `backend/tests/test_patch_graph.py` — PATCH graph tests for slug + schemas
- `backend/pytest.ini`
- `backend/alembic/versions/b3c4d5e6f7a8_add_graph_versioning_schemas_slugs.py` — migration
- `backend/app/services/__init__.py`
- `backend/app/services/publishing.py` — publish validation + freeze logic

**Modified:**
- `backend/requirements.txt` — add `pytest`, `pytest-asyncio`, `asgi-lifespan`
- `backend/app/models/graph.py` — new `GraphVersion` model + new Graph columns
- `backend/app/models/user.py` — `Org.slug`
- `backend/app/schemas/graph.py` — `GraphVersionOut`, extended Graph schemas
- `backend/app/routers/graphs.py` — new endpoints
- `backend/app/seed.py` — slug, schemas, auto-publish v1

### Frontend

**New:**
- `frontend/src/components/GraphDetail/index.tsx` — shell with header + tabs
- `frontend/src/components/GraphDetail/OverviewTab.tsx`
- `frontend/src/components/GraphDetail/VersionsTab.tsx`
- `frontend/src/components/GraphDetail/PublishModal.tsx`
- `frontend/src/components/shared/JsonSchemaEditor.tsx`
- `frontend/src/components/GraphEditor/SchemasDrawer.tsx`

**Modified:**
- `frontend/src/types/index.ts` — `GraphVersion`, `GraphVersionSummary`, schema fields on Graph
- `frontend/src/api/client.ts` — `publishGraph`, `listGraphVersions`, `getGraphVersion`, patch updates for slug/schemas
- `frontend/src/App.tsx` — route graph clicks through `GraphDetail` instead of directly into `GraphEditor`
- `frontend/src/components/GraphList/index.tsx` — minor: show slug on cards
- `frontend/src/components/GraphEditor/index.tsx` — add Schemas toolbar button; change back button to return to `GraphDetail`

---

## Task 1: Bootstrap pytest harness

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1: Add test dependencies**

Append to `backend/requirements.txt`:
```
pytest==8.4.1
pytest-asyncio==1.0.0
asgi-lifespan==2.1.0
```

(`aiosqlite` is already pinned. `asgi-lifespan` gives us proper startup/shutdown in tests so the FastAPI lifespan runs migrations into the in-memory SQLite.)

- [ ] **Step 2: Create pytest config**

Write `backend/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
pythonpath = .
```

- [ ] **Step 3: Create the tests package marker**

Write `backend/tests/__init__.py` — empty file.

- [ ] **Step 4: Write shared conftest with DB + ASGI client fixtures**

Write `backend/tests/conftest.py`:
```python
"""
Shared pytest fixtures.

- A fresh in-memory SQLite database per test via a session-scoped engine
  with function-scoped `SAVEPOINT` rollbacks (no data bleeds between tests).
- An httpx.AsyncClient wired to the FastAPI app via ASGITransport so we can
  hit endpoints directly without running uvicorn.
- Alembic migrations applied once at session start.
"""

import asyncio
import os

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set the DB URL BEFORE any app modules are imported
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DEBUG", "false")  # disable seed during tests — tests set up their own data
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    """Per-test session with rollback so no data bleeds across tests."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    TestSessionLocal = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncClient:
    """httpx client talking to the FastAPI app with the test session injected."""
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()
```

Note: this uses `Base.metadata.create_all` rather than running Alembic, because Alembic's `render_as_batch` mode and our migration chain both work against real Postgres/SQLite but `create_all` is faster and sufficient for unit tests. Alembic migration correctness is a separate concern verified by the compose up + seed path.

- [ ] **Step 5: Write a smoke test**

Write `backend/tests/test_smoke.py`:
```python
"""Sanity check — confirms pytest, the fixtures, and the app all wire together."""

async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_graphs_list_empty(client):
    response = await client.get("/api/v1/graphs/")
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 6: Run the smoke tests**

Run from the `backend/` directory:
```bash
docker compose exec backend pip install pytest==8.4.1 pytest-asyncio==1.0.0 asgi-lifespan==2.1.0
docker compose exec backend pytest tests/test_smoke.py -v
```

Expected output: `2 passed`.

If running outside docker, install the deps into the local venv and run `cd backend && pytest tests/test_smoke.py -v`.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/pytest.ini backend/tests/
git commit -m "test: bootstrap pytest harness with in-memory SQLite fixtures"
```

---

## Task 2: Alembic migration for graph versioning, schemas, slugs

**Files:**
- Create: `backend/alembic/versions/b3c4d5e6f7a8_add_graph_versioning_schemas_slugs.py`

- [ ] **Step 1: Write the migration file**

Create `backend/alembic/versions/b3c4d5e6f7a8_add_graph_versioning_schemas_slugs.py`:

```python
"""add graph_versions table, schemas, slugs

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # orgs.slug — nullable first, backfill, then enforce unique
    op.add_column('orgs', sa.Column('slug', sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE orgs SET slug = 'demo' WHERE slug IS NULL"
    )
    with op.batch_alter_table('orgs') as batch_op:
        batch_op.alter_column('slug', existing_type=sa.String(length=128), nullable=False)
        batch_op.create_unique_constraint('uq_orgs_slug', ['slug'])

    # graphs.slug + schema + version fields — nullable first, backfill known seeded row, enforce unique
    op.add_column('graphs', sa.Column('slug', sa.String(length=128), nullable=True))
    op.add_column('graphs', sa.Column('input_schema', sa.JSON(), nullable=True))
    op.add_column('graphs', sa.Column('output_schema', sa.JSON(), nullable=True))
    op.add_column('graphs', sa.Column('latest_published_version_id', sa.Uuid(), nullable=True))
    op.add_column('graphs', sa.Column('retention_days', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('graphs', sa.Column('test_examples', sa.JSON(), nullable=True))

    # Backfill the seeded graph with its canonical slug
    op.execute(
        "UPDATE graphs SET slug = 'change-risk-analyzer' "
        "WHERE id = '00000000-0000-0000-0000-000000000020' AND slug IS NULL"
    )

    with op.batch_alter_table('graphs') as batch_op:
        batch_op.create_unique_constraint(
            'uq_graphs_org_slug', ['org_id', 'slug']
        )

    # graph_versions table
    op.create_table(
        'graph_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('definition_json', sa.JSON(), nullable=False),
        sa.Column('input_schema', sa.JSON(), nullable=True),
        sa.Column('output_schema', sa.JSON(), nullable=True),
        sa.Column('published_by', sa.Uuid(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['graph_id'], ['graphs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('graph_id', 'version', name='uq_graph_versions_graph_id_version'),
    )
    op.create_index(
        'ix_graph_versions_graph_id',
        'graph_versions',
        ['graph_id'],
    )

    # latest_published_version_id FK — defined separately so graph_versions exists first
    with op.batch_alter_table('graphs') as batch_op:
        batch_op.create_foreign_key(
            'fk_graphs_latest_published_version_id',
            'graph_versions',
            ['latest_published_version_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('graphs') as batch_op:
        batch_op.drop_constraint('fk_graphs_latest_published_version_id', type_='foreignkey')

    op.drop_index('ix_graph_versions_graph_id', table_name='graph_versions')
    op.drop_table('graph_versions')

    with op.batch_alter_table('graphs') as batch_op:
        batch_op.drop_constraint('uq_graphs_org_slug', type_='unique')

    op.drop_column('graphs', 'test_examples')
    op.drop_column('graphs', 'retention_days')
    op.drop_column('graphs', 'latest_published_version_id')
    op.drop_column('graphs', 'output_schema')
    op.drop_column('graphs', 'input_schema')
    op.drop_column('graphs', 'slug')

    with op.batch_alter_table('orgs') as batch_op:
        batch_op.drop_constraint('uq_orgs_slug', type_='unique')

    op.drop_column('orgs', 'slug')
```

Note: `with op.batch_alter_table(...)` is used for constraint additions so the migration is SQLite-compatible — required for the test harness and also safe against Postgres.

- [ ] **Step 2: Run the migration against the dev database**

```bash
docker compose up -d postgres
docker compose exec backend alembic upgrade head
```

Expected output: `INFO  [alembic.runtime.migration] Running upgrade a2b3c4d5e6f7 -> b3c4d5e6f7a8, add graph_versions table, schemas, slugs`.

- [ ] **Step 3: Verify the new columns and table landed**

```bash
docker compose exec postgres psql -U agent -d agent_platform -c "\d graphs"
docker compose exec postgres psql -U agent -d agent_platform -c "\d graph_versions"
docker compose exec postgres psql -U agent -d agent_platform -c "SELECT slug FROM graphs"
```

Expected: `graphs` has `slug`, `input_schema`, `output_schema`, `latest_published_version_id`, `retention_days`, `test_examples`. `graph_versions` exists with the expected columns. The existing seeded graph has `slug = 'change-risk-analyzer'`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/b3c4d5e6f7a8_add_graph_versioning_schemas_slugs.py
git commit -m "feat(db): migration for graph versioning, schemas, slugs"
```

---

## Task 3: ORM models — `GraphVersion` + new columns on `Graph` and `Org`

**Files:**
- Modify: `backend/app/models/graph.py`
- Modify: `backend/app/models/user.py`

- [ ] **Step 1: Add the `slug` column to the `Org` model**

Open `backend/app/models/user.py` and add `slug` to the `Org` class after `name`:
```python
slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
```

- [ ] **Step 2: Add the new columns to the `Graph` model**

Open `backend/app/models/graph.py`. Add these columns to the `Graph` class (after `parent_graph_id`):
```python
    slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latest_published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("graph_versions.id", ondelete="SET NULL"), nullable=True
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    test_examples: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

Also add a `versions` relationship to `Graph`:
```python
    versions: Mapped[list["GraphVersion"]] = relationship(
        "GraphVersion",
        back_populates="graph",
        cascade="all, delete-orphan",
        foreign_keys="GraphVersion.graph_id",
        order_by="GraphVersion.version.desc()",
    )
```

- [ ] **Step 3: Add the `GraphVersion` model**

In the same file, append the `GraphVersion` class:
```python
class GraphVersion(Base):
    """
    Immutable snapshot of a graph at publish time. The runner executes
    a specific GraphVersion row, never the live draft (except for editor
    test runs that explicitly target the draft).

    `version` is 1-indexed and unique within a graph.
    """

    __tablename__ = "graph_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    graph: Mapped["Graph"] = relationship(
        "Graph",
        back_populates="versions",
        foreign_keys=[graph_id],
    )
```

- [ ] **Step 4: Run the smoke tests to confirm models still import cleanly**

```bash
cd backend && pytest tests/test_smoke.py -v
```

Expected: `2 passed`. If the test fails with a model resolution error, the `foreign_keys=` hint on `Graph.versions` may need adjustment.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/graph.py backend/app/models/user.py
git commit -m "feat(models): GraphVersion model and new columns for versioning and schemas"
```

---

## Task 4: Pydantic schemas for graph versions

**Files:**
- Modify: `backend/app/schemas/graph.py`

- [ ] **Step 1: Add `GraphVersionSummary` and `GraphVersionOut` schemas**

Open `backend/app/schemas/graph.py` and append:
```python
class GraphVersionSummary(BaseModel):
    """Lightweight version info — for lists."""
    id: uuid.UUID
    version: int
    published_by: uuid.UUID
    published_at: datetime
    notes: str | None = None

    model_config = {"from_attributes": True}


class GraphVersionOut(BaseModel):
    """Full version record including frozen definition + schemas."""
    id: uuid.UUID
    graph_id: uuid.UUID
    version: int
    definition_json: dict
    input_schema: dict | None = None
    output_schema: dict | None = None
    published_by: uuid.UUID
    published_at: datetime
    notes: str | None = None

    model_config = {"from_attributes": True}


class GraphPublishBody(BaseModel):
    """Body for POST /graphs/{id}/publish."""
    notes: str | None = None
```

- [ ] **Step 2: Extend `GraphBase` and `GraphOut` with the new fields**

Find the existing `GraphBase` (it has `name`, `description`). Add:
```python
    slug: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    retention_days: int = 30
    test_examples: list[dict] | None = None
```

In `GraphOut`, add these fields:
```python
    latest_published_version_id: uuid.UUID | None = None
    latest_version_number: int | None = None  # derived, populated in router
```

(`latest_version_number` is a server-computed convenience: the router reads `latest_published_version_id`'s `version` column and includes it so the UI doesn't need a second lookup.)

- [ ] **Step 3: Extend `GraphUpdate` to allow schema + slug changes**

If there's an existing `GraphUpdate` schema in the file, add:
```python
    slug: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    retention_days: int | None = None
```

If there is no dedicated update schema yet, the existing PUT handler in `routers/graphs.py` accepts the same shape as Create — which is fine, but PATCH (added in Task 7) needs a dedicated optional-fields model.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/graph.py
git commit -m "feat(schemas): GraphVersionOut, GraphPublishBody, extended Graph fields"
```

---

## Task 5: Publish validation service

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/publishing.py`
- Create: `backend/tests/test_publish_validation.py`

- [ ] **Step 1: Create the services package**

Write `backend/app/services/__init__.py` — empty file.

- [ ] **Step 2: Write the failing tests**

Write `backend/tests/test_publish_validation.py`:
```python
"""Publish validation rules — pure functions, no DB required."""

import pytest

from app.services.publishing import validate_publishable, PublishValidationError


def test_empty_definition_rejects():
    with pytest.raises(PublishValidationError, match="at least one node"):
        validate_publishable(
            definition={"nodes": [], "edges": []},
            known_agent_ids=set(),
            known_mcp_server_ids=set(),
        )


def test_missing_nodes_key_rejects():
    with pytest.raises(PublishValidationError, match="at least one node"):
        validate_publishable(
            definition={},
            known_agent_ids=set(),
            known_mcp_server_ids=set(),
        )


def test_dangling_agent_ref_rejects():
    definition = {
        "nodes": [
            {
                "key": "assess",
                "type": "a2a",
                "config": {"agent_id": "00000000-0000-0000-0000-000000000999"},
            }
        ],
        "edges": [],
    }
    with pytest.raises(PublishValidationError, match="agent .* not found"):
        validate_publishable(
            definition=definition,
            known_agent_ids=set(),
            known_mcp_server_ids=set(),
        )


def test_dangling_mcp_scalar_ref_rejects():
    definition = {
        "nodes": [
            {
                "key": "fetch",
                "type": "mcp_tool",
                "config": {"mcp_server_id": "00000000-0000-0000-0000-000000000999"},
            }
        ],
        "edges": [],
    }
    with pytest.raises(PublishValidationError, match="mcp server .* not found"):
        validate_publishable(
            definition=definition,
            known_agent_ids=set(),
            known_mcp_server_ids=set(),
        )


def test_dangling_mcp_list_ref_rejects():
    definition = {
        "nodes": [
            {
                "key": "react",
                "type": "agent",
                "config": {
                    "mcp_server_ids": ["00000000-0000-0000-0000-000000000999"]
                },
            }
        ],
        "edges": [],
    }
    with pytest.raises(PublishValidationError, match="mcp server .* not found"):
        validate_publishable(
            definition=definition,
            known_agent_ids=set(),
            known_mcp_server_ids=set(),
        )


def test_valid_passes():
    definition = {
        "nodes": [
            {"key": "classify", "type": "llm", "config": {}},
        ],
        "edges": [
            {"from": "__start__", "to": "classify", "condition": None},
            {"from": "classify", "to": "__end__", "condition": None},
        ],
    }
    # Should not raise
    validate_publishable(
        definition=definition,
        known_agent_ids=set(),
        known_mcp_server_ids=set(),
    )


def test_valid_with_resolved_refs_passes():
    agent_id = "00000000-0000-0000-0000-000000000011"
    mcp_id = "00000000-0000-0000-0000-000000000010"
    definition = {
        "nodes": [
            {"key": "assess", "type": "a2a", "config": {"agent_id": agent_id}},
            {"key": "fetch", "type": "mcp_tool", "config": {"mcp_server_id": mcp_id}},
        ],
        "edges": [],
    }
    validate_publishable(
        definition=definition,
        known_agent_ids={agent_id},
        known_mcp_server_ids={mcp_id},
    )
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
cd backend && pytest tests/test_publish_validation.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'app.services.publishing'` or `ImportError: cannot import name 'validate_publishable'`.

- [ ] **Step 4: Implement the validation function**

Write `backend/app/services/publishing.py`:
```python
"""
Publish validation: refuses to publish a graph draft that would break at run time.

Rules enforced (from the spec §9):
  - Draft must contain at least one node
  - All agent_id references must resolve to an existing Agent
  - All mcp_server_id and mcp_server_ids references must resolve to an existing MCPServer
  - Missing input_schema or output_schema is a WARNING, not a hard fail (recorded on
    the returned warnings list)
"""

from __future__ import annotations

from dataclasses import dataclass


class PublishValidationError(ValueError):
    """Raised when a draft cannot be published."""


@dataclass
class PublishValidation:
    """Result of a publish pre-check."""
    warnings: list[str]


def validate_publishable(
    *,
    definition: dict,
    known_agent_ids: set[str],
    known_mcp_server_ids: set[str],
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> PublishValidation:
    """
    Validate that the draft can be published. Raises PublishValidationError
    on any hard failure; returns a PublishValidation with soft warnings otherwise.

    Callers are responsible for loading the sets of known agent/mcp server ids
    (via a simple `select id from agents / mcp_servers where org_id = ?`).
    """
    nodes = (definition or {}).get("nodes") or []
    if not nodes:
        raise PublishValidationError("Graph must have at least one node to publish.")

    for node in nodes:
        cfg = node.get("config") or {}
        node_key = node.get("key", "<unnamed>")

        agent_id = cfg.get("agent_id")
        if agent_id and agent_id not in known_agent_ids:
            raise PublishValidationError(
                f"Node {node_key!r}: agent {agent_id} not found. "
                f"The referenced agent may have been deleted — remove or "
                f"repoint the reference before publishing."
            )

        mcp_id = cfg.get("mcp_server_id")
        if mcp_id and mcp_id not in known_mcp_server_ids:
            raise PublishValidationError(
                f"Node {node_key!r}: mcp server {mcp_id} not found. "
                f"Remove or repoint the reference before publishing."
            )

        for mcp_id in cfg.get("mcp_server_ids") or []:
            if mcp_id not in known_mcp_server_ids:
                raise PublishValidationError(
                    f"Node {node_key!r}: mcp server {mcp_id} not found "
                    f"in mcp_server_ids list. Remove or repoint before publishing."
                )

    warnings: list[str] = []
    if not input_schema:
        warnings.append("No input_schema declared — consumers cannot validate requests.")
    if not output_schema:
        warnings.append("No output_schema declared — API docs will be incomplete.")

    return PublishValidation(warnings=warnings)
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
cd backend && pytest tests/test_publish_validation.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ backend/tests/test_publish_validation.py
git commit -m "feat(services): publish validation service with ref checking"
```

---

## Task 6: `POST /graphs/{id}/publish` endpoint

**Files:**
- Modify: `backend/app/routers/graphs.py`
- Create: `backend/tests/test_publish.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_publish.py`:
```python
"""End-to-end publish endpoint tests with DB + FastAPI client."""

import uuid

import pytest
from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph, GraphVersion
from app.models.user import Org, User


async def _seed_basic(db_session):
    """Create the minimum rows needed for graph operations in tests."""
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID,
        email="test@example.com",
        display_name="Test User",
        org_id=DEV_ORG_ID,
    ))
    graph = Graph(
        id=uuid.uuid4(),
        name="Test Graph",
        description="A graph for publish tests",
        slug="test-graph",
        version=1,
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [
                {"key": "greet", "type": "llm", "config": {"system_prompt": "Hi"}},
            ],
            "edges": [
                {"from": "__start__", "to": "greet", "condition": None},
                {"from": "greet", "to": "__end__", "condition": None},
            ],
        },
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        output_schema={"type": "object"},
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_publish_creates_version_1(client, db_session):
    graph = await _seed_basic(db_session)

    response = await client.post(
        f"/api/v1/graphs/{graph.id}/publish",
        json={"notes": "First release"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["notes"] == "First release"
    assert body["input_schema"] == {"type": "object", "properties": {"name": {"type": "string"}}}
    assert body["definition_json"]["nodes"][0]["key"] == "greet"


async def test_publish_increments_version(client, db_session):
    graph = await _seed_basic(db_session)

    r1 = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r1.status_code == 201 and r1.json()["version"] == 1

    r2 = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v2"})
    assert r2.status_code == 201 and r2.json()["version"] == 2


async def test_publish_updates_latest_pointer(client, db_session):
    graph = await _seed_basic(db_session)

    r = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r.status_code == 201
    published_version_id = r.json()["id"]

    # Refetch the graph and check the pointer was updated
    refreshed = await client.get(f"/api/v1/graphs/{graph.id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["latest_published_version_id"] == published_version_id
    assert refreshed.json()["latest_version_number"] == 1


async def test_publish_empty_draft_rejected(client, db_session):
    graph = Graph(
        id=uuid.uuid4(),
        name="Empty",
        slug="empty",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    # Need org and user first
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    db_session.add(graph)
    await db_session.flush()

    r = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={})
    assert r.status_code == 422
    assert "at least one node" in r.json()["error"]


async def test_publish_graph_not_found(client):
    r = await client.post(
        f"/api/v1/graphs/{uuid.uuid4()}/publish",
        json={},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests — all should fail**

```bash
cd backend && pytest tests/test_publish.py -v
```

Expected: all fail with `404` or `405` (endpoint not implemented yet).

- [ ] **Step 3: Implement the endpoint**

Open `backend/app/routers/graphs.py`. Add these imports at the top:
```python
from app.models.agent import Agent
from app.models.graph import Graph, GraphNode, GraphEdge, GraphVersion
from app.models.mcp_server import MCPServer
from app.schemas.graph import GraphPublishBody, GraphVersionOut
from app.services.publishing import PublishValidationError, validate_publishable
```
(Keep the existing imports. Deduplicate if needed — `Graph`, `GraphNode`, `GraphEdge` are already imported there.)

Then add this handler below the existing graph handlers:
```python
@router.post(
    "/{graph_id}/publish",
    response_model=GraphVersionOut,
    status_code=201,
)
async def publish_graph(
    graph_id: uuid.UUID,
    body: GraphPublishBody,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # Load known agent + mcp server ids for ref validation
    agent_result = await db.execute(select(Agent.id).where(Agent.org_id == graph.org_id))
    mcp_result = await db.execute(select(MCPServer.id).where(MCPServer.org_id == graph.org_id))
    known_agent_ids = {str(a) for (a,) in agent_result.all()}
    known_mcp_ids = {str(m) for (m,) in mcp_result.all()}

    try:
        validate_publishable(
            definition=graph.definition_json or {},
            known_agent_ids=known_agent_ids,
            known_mcp_server_ids=known_mcp_ids,
            input_schema=graph.input_schema,
            output_schema=graph.output_schema,
        )
    except PublishValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Determine next version number
    latest = await db.execute(
        select(func.max(GraphVersion.version)).where(GraphVersion.graph_id == graph.id)
    )
    next_version = (latest.scalar() or 0) + 1

    version = GraphVersion(
        graph_id=graph.id,
        version=next_version,
        definition_json=graph.definition_json,
        input_schema=graph.input_schema,
        output_schema=graph.output_schema,
        published_by=graph.created_by,  # placeholder until auth lands in Plan C
        notes=body.notes,
    )
    db.add(version)
    await db.flush()

    graph.latest_published_version_id = version.id
    await db.flush()
    await db.refresh(version)
    return version
```

Make sure `from sqlalchemy import func` is in the imports at the top of the file (add it if missing).

- [ ] **Step 4: Update `GET /graphs/{id}` to include `latest_version_number`**

Find the existing handler `get_graph` (or similar) in `routers/graphs.py`. Before returning the graph, load the latest version number:
```python
    # Populate latest_version_number from the GraphVersion row
    latest_version_number = None
    if graph.latest_published_version_id:
        v = await db.execute(
            select(GraphVersion.version).where(GraphVersion.id == graph.latest_published_version_id)
        )
        latest_version_number = v.scalar_one_or_none()

    # Build the response dict manually so we can include the derived field
    data = {
        "id": graph.id,
        "name": graph.name,
        "description": graph.description,
        "slug": graph.slug,
        "input_schema": graph.input_schema,
        "output_schema": graph.output_schema,
        "latest_published_version_id": graph.latest_published_version_id,
        "latest_version_number": latest_version_number,
        "retention_days": graph.retention_days,
        "test_examples": graph.test_examples,
        "version": graph.version,
        "parent_graph_id": graph.parent_graph_id,
        "created_by": graph.created_by,
        "org_id": graph.org_id,
        "definition_json": graph.definition_json,
        "nodes": [...],  # keep existing node/edge loading
        "edges": [...],
        "created_at": graph.created_at,
        "updated_at": graph.updated_at,
    }
    return data
```
(If the handler currently returns the ORM instance directly, refactor it to the dict shape above. Preserve the existing nodes/edges loading logic exactly — only add the `latest_version_number` field.)

- [ ] **Step 5: Run the tests again**

```bash
cd backend && pytest tests/test_publish.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/graphs.py backend/tests/test_publish.py
git commit -m "feat(api): POST /graphs/{id}/publish with ref validation"
```

---

## Task 7: `GET /graphs/{id}/versions` and `GET /graphs/{id}/versions/{v}`

**Files:**
- Modify: `backend/app/routers/graphs.py`
- Create: `backend/tests/test_versions.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_versions.py`:
```python
"""Version list + detail endpoint tests."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID,
        email="test@example.com",
        display_name="Test User",
        org_id=DEV_ORG_ID,
    ))
    graph = Graph(
        id=uuid.uuid4(),
        name="Test Graph",
        slug="test-graph",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "greet", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "greet", "condition": None},
                {"from": "greet", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_list_versions_empty(client, db_session):
    graph = await _seed(db_session)
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_versions_after_publish(client, db_session):
    graph = await _seed(db_session)
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v1"})
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v2"})
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    # Newest first
    assert body[0]["version"] == 2 and body[0]["notes"] == "v2"
    assert body[1]["version"] == 1 and body[1]["notes"] == "v1"


async def test_get_version_detail(client, db_session):
    graph = await _seed(db_session)
    await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v1"})
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions/1")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["notes"] == "v1"
    assert body["definition_json"]["nodes"][0]["key"] == "greet"


async def test_get_version_not_found(client, db_session):
    graph = await _seed(db_session)
    r = await client.get(f"/api/v1/graphs/{graph.id}/versions/99")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_versions.py -v
```

Expected: all 4 fail with 404 or 405.

- [ ] **Step 3: Implement the list and detail endpoints**

In `backend/app/routers/graphs.py`, add:
```python
from app.schemas.graph import GraphVersionSummary  # add to imports if missing


@router.get(
    "/{graph_id}/versions",
    response_model=list[GraphVersionSummary],
)
async def list_graph_versions(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    result = await db.execute(
        select(GraphVersion)
        .where(GraphVersion.graph_id == graph_id)
        .order_by(GraphVersion.version.desc())
    )
    return result.scalars().all()


@router.get(
    "/{graph_id}/versions/{version}",
    response_model=GraphVersionOut,
)
async def get_graph_version(
    graph_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GraphVersion).where(
            GraphVersion.graph_id == graph_id,
            GraphVersion.version == version,
        )
    )
    gv = result.scalar_one_or_none()
    if not gv:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return gv
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_versions.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/graphs.py backend/tests/test_versions.py
git commit -m "feat(api): GET /graphs/{id}/versions list and detail"
```

---

## Task 8: Extended `PATCH /graphs/{id}` for slug + schemas

**Files:**
- Modify: `backend/app/routers/graphs.py`
- Create: `backend/tests/test_patch_graph.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_patch_graph.py`:
```python
"""PATCH /graphs/{id} — slug + schema updates."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID,
        email="test@example.com",
        display_name="Test User",
        org_id=DEV_ORG_ID,
    ))
    graph = Graph(
        id=uuid.uuid4(),
        name="Test Graph",
        slug="original-slug",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_patch_slug(client, db_session):
    graph = await _seed(db_session)
    r = await client.patch(
        f"/api/v1/graphs/{graph.id}",
        json={"slug": "new-slug"},
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "new-slug"


async def test_patch_schemas(client, db_session):
    graph = await _seed(db_session)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    r = await client.patch(
        f"/api/v1/graphs/{graph.id}",
        json={"input_schema": schema, "output_schema": schema},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["input_schema"] == schema
    assert body["output_schema"] == schema


async def test_patch_slug_collision_within_org(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    a = Graph(id=uuid.uuid4(), name="A", slug="alpha",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    b = Graph(id=uuid.uuid4(), name="B", slug="beta",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add_all([a, b])
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/graphs/{b.id}",
        json={"slug": "alpha"},
    )
    assert r.status_code == 409
    assert "slug" in r.json()["error"].lower()
```

- [ ] **Step 2: Run tests**

```bash
cd backend && pytest tests/test_patch_graph.py -v
```

Expected: fails (endpoint missing or the existing PUT handler doesn't accept these fields or doesn't handle PATCH).

- [ ] **Step 3: Add the PATCH handler**

In `backend/app/routers/graphs.py`, add:
```python
from app.schemas.graph import GraphUpdate  # reuse or add to imports


@router.patch("/{graph_id}", response_model=GraphOut)
async def patch_graph(
    graph_id: uuid.UUID,
    body: GraphUpdate,
    db: AsyncSession = Depends(get_db),
):
    graph = await db.get(Graph, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    updates = body.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] is not None:
        # Check uniqueness per (org_id, slug)
        dup = await db.execute(
            select(Graph).where(
                Graph.org_id == graph.org_id,
                Graph.slug == updates["slug"],
                Graph.id != graph.id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"slug '{updates['slug']}' already in use by another graph in this org",
            )

    for field, value in updates.items():
        setattr(graph, field, value)

    await db.flush()
    await db.refresh(graph)
    # Reuse the existing get_graph response builder (refactor into a helper if needed)
    return await _graph_to_response(graph, db)
```

If the existing PUT handler already does some of this, refactor the response-building logic into a helper `async def _graph_to_response(graph, db) -> dict:` that both handlers can call. Keep the existing PUT behavior unchanged.

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_patch_graph.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/graphs.py backend/tests/test_patch_graph.py
git commit -m "feat(api): PATCH /graphs/{id} with slug and schema updates"
```

---

## Task 9: Seed update — slug, schemas, auto-publish v1

**Files:**
- Modify: `backend/app/seed.py`

- [ ] **Step 1: Add slug and schemas to the desired state**

Open `backend/app/seed.py` and update `_desired_graph_meta()`:
```python
def _desired_graph_meta() -> dict:
    return {
        "name": "Change Request Risk Analyzer",
        "slug": "change-risk-analyzer",
        "description": (
            "Analyzes a software change request end-to-end. "
            "Classifies risk (high/medium/low), fetches service dependencies, "
            "calls a specialist A2A agent for high-risk changes, "
            "and generates a final markdown report."
        ),
        "input_schema": _SEED_INPUT_SCHEMA,
        "output_schema": _SEED_OUTPUT_SCHEMA,
    }
```

Add these constants at module level (right after `SEED_A2A_URL`):
```python
_SEED_INPUT_SCHEMA = {
    "type": "object",
    "required": ["title", "description", "affected_services"],
    "properties": {
        "title": {
            "type": "string",
            "description": "Short title of the change request",
        },
        "description": {
            "type": "string",
            "description": "Full description of what's being changed and why",
        },
        "affected_services": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names of services affected by the change",
        },
        "proposed_window": {
            "type": "string",
            "description": "When the change will happen (e.g. 'Sat 02:00 UTC')",
        },
    },
}

_SEED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "object",
            "properties": {
                "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
                "key_concerns": {"type": "array", "items": {"type": "string"}},
            },
        },
        "report": {
            "type": "string",
            "description": "Final markdown risk report",
        },
    },
}
```

- [ ] **Step 2: Update `_upsert_org` to include the slug**

In `backend/app/seed.py`, update `_upsert_org`:
```python
async def _upsert_org(db, stats: SeedStats) -> None:
    org = await db.get(Org, DEV_ORG_ID)
    if not org:
        db.add(Org(id=DEV_ORG_ID, name="Demo Org", slug="demo"))
        stats["inserted"] += 1
    else:
        changed = False
        if org.slug != "demo":
            org.slug = "demo"
            changed = True
        if changed:
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
```

- [ ] **Step 3: Auto-publish v1 on first seed**

After `_upsert_graph` returns, in the main `seed()` function, add a new helper call:
```python
async def seed() -> None:
    stats = _new_stats()

    async with AsyncSessionLocal() as db:
        await _upsert_org(db, stats)
        await db.flush()
        await _upsert_user(db, stats)
        await db.flush()
        await _upsert_mcp_server(db, stats)
        await db.flush()
        await _upsert_agent(db, stats)
        await db.flush()
        await _upsert_graph(db, stats)
        await db.flush()
        await _ensure_seed_graph_published(db, stats)
        await db.commit()

    log.info("seed_complete", extra={...})
```

Add the new helper:
```python
async def _ensure_seed_graph_published(db, stats: SeedStats) -> None:
    """
    Ensure the seed graph has at least one published version. Idempotent:
    if a version already exists, this is a no-op.
    """
    from sqlalchemy import select
    from app.models.graph import Graph, GraphVersion

    graph = await db.get(Graph, SEED_GRAPH_ID)
    if not graph:
        return

    existing = await db.execute(
        select(GraphVersion).where(GraphVersion.graph_id == SEED_GRAPH_ID)
    )
    if existing.first():
        return  # already published

    v1 = GraphVersion(
        graph_id=graph.id,
        version=1,
        definition_json=graph.definition_json,
        input_schema=graph.input_schema,
        output_schema=graph.output_schema,
        published_by=DEV_USER_ID,
        notes="Initial seed publish",
    )
    db.add(v1)
    await db.flush()
    graph.latest_published_version_id = v1.id
    stats["inserted"] += 1
    log.info("seeded_graph_v1_published")
```

- [ ] **Step 4: Restart backend and verify**

```bash
docker compose restart backend
docker compose logs backend --tail 20
```

Expected log lines include `seeded_graph_v1_published` and `seed_complete`.

Verify via curl:
```bash
curl http://localhost:8000/api/v1/graphs/00000000-0000-0000-0000-000000000020/versions | jq
```

Expected: one version with `"version": 1`, `"notes": "Initial seed publish"`.

- [ ] **Step 5: Run all backend tests to confirm seed changes didn't break anything**

```bash
cd backend && pytest -v
```

Expected: all tests pass (smoke + publish validation + publish endpoint + versions + patch).

- [ ] **Step 6: Commit**

```bash
git add backend/app/seed.py
git commit -m "feat(seed): slug, schemas, and auto-publish v1 for seed graph"
```

---

## Task 10: Frontend types and API client additions

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add new types**

Open `frontend/src/types/index.ts` and append:
```typescript
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
```

Also update the existing `Graph` interface to include the new fields:
```typescript
export interface Graph {
  id: string;
  name: string;
  description: string | null;
  slug: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  latest_published_version_id: string | null;
  latest_version_number: number | null;
  retention_days: number;
  test_examples: unknown[] | null;
  version: number;
  parent_graph_id: string | null;
  created_by: string;
  org_id: string;
  definition_json: Record<string, unknown>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  created_at: string;
  updated_at: string;
}
```

And update `GraphSummary` to include `slug` and `latest_version_number`:
```typescript
export interface GraphSummary {
  id: string;
  name: string;
  description: string | null;
  slug: string | null;
  latest_version_number: number | null;
  version: number;
  parent_graph_id: string | null;
  created_by: string;
  org_id: string;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Add API client functions**

Open `frontend/src/api/client.ts`. Update the imports to include the new types:
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
  Usage,
} from "../types";
```

Add these functions:
```typescript
export const patchGraph = (
  id: string,
  body: { name?: string; description?: string; slug?: string; input_schema?: Record<string, unknown> | null; output_schema?: Record<string, unknown> | null; retention_days?: number }
): Promise<Graph> => api.patch(`/graphs/${id}`, body).then((r) => r.data);

export const publishGraph = (id: string, body: GraphPublishBody): Promise<GraphVersion> =>
  api.post(`/graphs/${id}/publish`, body).then((r) => r.data);

export const listGraphVersions = (id: string): Promise<GraphVersionSummary[]> =>
  api.get(`/graphs/${id}/versions`).then((r) => r.data);

export const getGraphVersion = (id: string, version: number): Promise<GraphVersion> =>
  api.get(`/graphs/${id}/versions/${version}`).then((r) => r.data);
```

- [ ] **Step 3: Run TypeScript compile to catch any fallout**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0. If there are errors, they'll likely be in files that destructure `Graph` or `GraphSummary` — fix them by adding the new fields or using optional chaining as appropriate.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(frontend): types and API client for graph versioning"
```

---

## Task 11: Shared `JsonSchemaEditor` component

**Files:**
- Create: `frontend/src/components/shared/JsonSchemaEditor.tsx`

- [ ] **Step 1: Write the component**

Write `frontend/src/components/shared/JsonSchemaEditor.tsx`:
```typescript
import { useEffect, useState } from "react";

/**
 * Minimal JSON Schema editor supporting the v1 subset:
 *   - object with flat properties
 *   - string, number, integer, boolean
 *   - string enum
 *   - array of primitives
 *   - one level of nested object
 *   - required field marking
 *   - description per field
 *
 * Has two modes:
 *   - visual: row-per-field editor
 *   - json: raw textarea
 *
 * Props:
 *   - value: current schema (JSON Schema dict)
 *   - onChange: called when the schema changes (visual edits or valid JSON edits)
 *   - readOnly: if true, renders a read-only field table
 */

interface Props {
  value: Record<string, unknown> | null;
  onChange?: (schema: Record<string, unknown>) => void;
  readOnly?: boolean;
}

type FieldType = "string" | "number" | "integer" | "boolean" | "enum" | "array" | "object";

interface FieldRow {
  name: string;
  type: FieldType;
  required: boolean;
  description: string;
  enumValues?: string[];     // for enum
  arrayItemType?: FieldType; // for array
}

// Minimal conversion: schema <-> rows
function schemaToRows(schema: Record<string, unknown> | null): FieldRow[] {
  if (!schema || schema.type !== "object") return [];
  const props = (schema.properties as Record<string, Record<string, unknown>>) ?? {};
  const required = new Set((schema.required as string[]) ?? []);
  return Object.entries(props).map(([name, def]) => {
    const type = inferFieldType(def);
    return {
      name,
      type,
      required: required.has(name),
      description: (def.description as string) ?? "",
      enumValues: (def.enum as string[]) ?? undefined,
      arrayItemType: type === "array"
        ? inferFieldType((def.items as Record<string, unknown>) ?? {})
        : undefined,
    };
  });
}

function inferFieldType(def: Record<string, unknown>): FieldType {
  if (def.enum) return "enum";
  const t = def.type as string;
  if (t === "array") return "array";
  if (t === "object") return "object";
  if (t === "integer") return "integer";
  if (t === "number") return "number";
  if (t === "boolean") return "boolean";
  return "string";
}

function rowsToSchema(rows: FieldRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const row of rows) {
    if (!row.name) continue;
    const fieldDef: Record<string, unknown> = {};
    if (row.description) fieldDef.description = row.description;
    switch (row.type) {
      case "enum":
        fieldDef.type = "string";
        fieldDef.enum = row.enumValues ?? [];
        break;
      case "array":
        fieldDef.type = "array";
        fieldDef.items = { type: row.arrayItemType ?? "string" };
        break;
      case "object":
        fieldDef.type = "object";
        fieldDef.properties = {};
        break;
      default:
        fieldDef.type = row.type;
    }
    properties[row.name] = fieldDef;
    if (row.required) required.push(row.name);
  }
  return {
    type: "object",
    ...(required.length ? { required } : {}),
    properties,
  };
}

export function JsonSchemaEditor({ value, onChange, readOnly = false }: Props) {
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [rows, setRows] = useState<FieldRow[]>(() => schemaToRows(value));
  const [jsonText, setJsonText] = useState(() =>
    value ? JSON.stringify(value, null, 2) : ""
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    setRows(schemaToRows(value));
    setJsonText(value ? JSON.stringify(value, null, 2) : "");
  }, [value]);

  const emit = (newRows: FieldRow[]) => {
    setRows(newRows);
    if (onChange) onChange(rowsToSchema(newRows));
  };

  const updateRow = (idx: number, patch: Partial<FieldRow>) => {
    emit(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => emit([...rows, { name: "", type: "string", required: false, description: "" }]);
  const removeRow = (idx: number) => emit(rows.filter((_, i) => i !== idx));

  if (readOnly) {
    return (
      <table style={styles.table}>
        <thead>
          <tr style={styles.headRow}>
            <th style={styles.th}>Field</th>
            <th style={styles.th}>Type</th>
            <th style={styles.th}>Description</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={3} style={styles.emptyCell}>No schema defined.</td></tr>
          ) : rows.map((r, i) => (
            <tr key={i}>
              <td style={styles.td}>
                <code style={styles.code}>{r.name}</code>
                {r.required && <span style={styles.requiredMark}> *</span>}
              </td>
              <td style={{ ...styles.td, fontFamily: "monospace", fontSize: 11, color: "#7c3aed" }}>
                {r.type === "array" ? `${r.arrayItemType ?? "string"}[]` : r.type}
              </td>
              <td style={{ ...styles.td, color: "#4b5563" }}>{r.description || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <div>
      <div style={styles.modeRow}>
        <button
          style={{ ...styles.modeBtn, ...(mode === "visual" ? styles.modeBtnActive : {}) }}
          onClick={() => setMode("visual")}
        >
          Visual
        </button>
        <button
          style={{ ...styles.modeBtn, ...(mode === "json" ? styles.modeBtnActive : {}) }}
          onClick={() => setMode("json")}
        >
          JSON
        </button>
      </div>

      {mode === "visual" ? (
        <div>
          {rows.map((row, i) => (
            <div key={i} style={styles.rowCard}>
              <div style={styles.rowLine}>
                <input
                  style={{ ...styles.input, flex: 2 }}
                  placeholder="field name"
                  value={row.name}
                  onChange={(e) => updateRow(i, { name: e.target.value })}
                />
                <select
                  style={{ ...styles.select, flex: 1 }}
                  value={row.type}
                  onChange={(e) => updateRow(i, { type: e.target.value as FieldType })}
                >
                  <option value="string">string</option>
                  <option value="number">number</option>
                  <option value="integer">integer</option>
                  <option value="boolean">boolean</option>
                  <option value="enum">enum</option>
                  <option value="array">array</option>
                </select>
                <label style={styles.reqCheck}>
                  <input
                    type="checkbox"
                    checked={row.required}
                    onChange={(e) => updateRow(i, { required: e.target.checked })}
                  />
                  required
                </label>
                <button style={styles.removeBtn} onClick={() => removeRow(i)}>×</button>
              </div>
              <input
                style={{ ...styles.input, marginTop: 4, width: "100%" }}
                placeholder="description (optional)"
                value={row.description}
                onChange={(e) => updateRow(i, { description: e.target.value })}
              />
              {row.type === "enum" && (
                <input
                  style={{ ...styles.input, marginTop: 4, width: "100%" }}
                  placeholder="comma-separated enum values"
                  value={(row.enumValues ?? []).join(", ")}
                  onChange={(e) =>
                    updateRow(i, {
                      enumValues: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    })
                  }
                />
              )}
              {row.type === "array" && (
                <select
                  style={{ ...styles.select, marginTop: 4, width: "100%" }}
                  value={row.arrayItemType ?? "string"}
                  onChange={(e) => updateRow(i, { arrayItemType: e.target.value as FieldType })}
                >
                  <option value="string">array of string</option>
                  <option value="number">array of number</option>
                  <option value="integer">array of integer</option>
                  <option value="boolean">array of boolean</option>
                </select>
              )}
            </div>
          ))}
          <button style={styles.addBtn} onClick={addRow}>+ Add field</button>
        </div>
      ) : (
        <div>
          <textarea
            style={styles.jsonArea}
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                setJsonError(null);
                setRows(schemaToRows(parsed));
                if (onChange) onChange(parsed);
              } catch (err) {
                setJsonError((err as Error).message);
              }
            }}
          />
          {jsonError && <div style={styles.errorBox}>{jsonError}</div>}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  modeRow: { display: "flex", gap: 6, marginBottom: 10 },
  modeBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "4px 12px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
  },
  modeBtnActive: { background: "#2563eb", color: "#fff", borderColor: "#2563eb" },
  rowCard: {
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    padding: 8,
    marginBottom: 6,
    background: "#fafafa",
  },
  rowLine: { display: "flex", gap: 6, alignItems: "center" },
  input: {
    border: "1px solid #d1d5db",
    borderRadius: 4,
    padding: "5px 8px",
    fontSize: 12,
    boxSizing: "border-box",
  },
  select: {
    border: "1px solid #d1d5db",
    borderRadius: 4,
    padding: "5px 8px",
    fontSize: 12,
    background: "#fff",
    cursor: "pointer",
  },
  reqCheck: { fontSize: 11, color: "#374151", display: "flex", alignItems: "center", gap: 4 },
  removeBtn: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#dc2626",
    borderRadius: 4,
    padding: "0 8px",
    cursor: "pointer",
    fontWeight: 700,
  },
  addBtn: {
    background: "#f3f4f6",
    border: "1px dashed #d1d5db",
    borderRadius: 5,
    padding: "6px 12px",
    cursor: "pointer",
    fontSize: 12,
    width: "100%",
    marginTop: 4,
  },
  jsonArea: {
    width: "100%",
    minHeight: 200,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: 8,
    fontFamily: "monospace",
    fontSize: 11,
    boxSizing: "border-box",
    resize: "vertical",
  },
  errorBox: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    padding: "6px 10px",
    borderRadius: 5,
    fontSize: 11,
    marginTop: 4,
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  headRow: { background: "#f9fafb" },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: 700,
    fontSize: 11,
    color: "#374151",
  },
  td: { padding: "7px 10px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  code: {
    fontFamily: "monospace",
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 3,
  },
  requiredMark: { color: "#dc2626", fontWeight: 700, fontSize: 11 },
  emptyCell: { padding: 12, textAlign: "center", color: "#9ca3af", fontSize: 12 },
};
```

- [ ] **Step 2: Type-check the component**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shared/JsonSchemaEditor.tsx
git commit -m "feat(frontend): shared JsonSchemaEditor component with visual and JSON modes"
```

---

## Task 12: Schemas drawer in the canvas editor

**Files:**
- Create: `frontend/src/components/GraphEditor/SchemasDrawer.tsx`
- Modify: `frontend/src/components/GraphEditor/index.tsx`

- [ ] **Step 1: Write the SchemasDrawer component**

Write `frontend/src/components/GraphEditor/SchemasDrawer.tsx`:
```typescript
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
  }, [open, graph.id]);

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

      {banner && (
        <div style={styles.banner}>{banner}</div>
      )}

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
```

- [ ] **Step 2: Add the "Schemas" button to the GraphEditor toolbar**

Open `frontend/src/components/GraphEditor/index.tsx`. Near the top of the component, add state:
```typescript
const [schemasOpen, setSchemasOpen] = useState(false);
```

In the toolbar JSX, add a button next to the existing Save / Clone buttons:
```tsx
<button style={styles.toolbarBtn} onClick={() => setSchemasOpen(true)}>
  Schemas
</button>
```

At the bottom of the component's return (alongside the other drawers/modals), render:
```tsx
{graph && (
  <SchemasDrawer
    open={schemasOpen}
    onClose={() => setSchemasOpen(false)}
    graph={graph}
  />
)}
```

Import at the top:
```typescript
import { SchemasDrawer } from "./SchemasDrawer";
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GraphEditor/SchemasDrawer.tsx frontend/src/components/GraphEditor/index.tsx
git commit -m "feat(frontend): schemas drawer in canvas editor toolbar"
```

---

## Task 13: `GraphDetail` shell component

**Files:**
- Create: `frontend/src/components/GraphDetail/index.tsx`

- [ ] **Step 1: Write the shell**

Write `frontend/src/components/GraphDetail/index.tsx`:
```typescript
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getGraph } from "../../api/client";
import type { Graph } from "../../types";
import { OverviewTab } from "./OverviewTab";
import { VersionsTab } from "./VersionsTab";
import { PublishModal } from "./PublishModal";

type Tab = "overview" | "api-docs" | "versions" | "keys" | "runs" | "test";

interface Props {
  graphId: string;
  onBack: () => void;
  onEdit: (graphId: string) => void;
}

const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
  { id: "overview", label: "Overview" },
  { id: "api-docs", label: "API Docs", disabled: true },
  { id: "versions", label: "Versions" },
  { id: "keys", label: "Keys", disabled: true },
  { id: "runs", label: "Runs", disabled: true },
  { id: "test", label: "Test", disabled: true },
];

export function GraphDetail({ graphId, onBack, onEdit }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [publishOpen, setPublishOpen] = useState(false);

  const { data: graph, isLoading } = useQuery<Graph>({
    queryKey: ["graph", graphId],
    queryFn: () => getGraph(graphId),
  });

  if (isLoading) return <div style={{ padding: 24 }}>Loading…</div>;
  if (!graph) return <div style={{ padding: 24 }}>Graph not found.</div>;

  const nextVersion = (graph.latest_version_number ?? 0) + 1;
  const canPublish = (graph.nodes?.length ?? 0) > 0;

  return (
    <div style={{ background: "#f9fafb", minHeight: "100vh" }}>
      <div style={styles.header}>
        <div style={styles.headerTop}>
          <button style={styles.backBtn} onClick={onBack}>← Graphs</button>
          <div style={styles.titleBlock}>
            <div style={styles.pathRow}>
              <code style={styles.path}>acme / {graph.slug ?? "untitled"}</code>
              {graph.latest_version_number && (
                <span style={styles.versionBadge}>v{graph.latest_version_number}</span>
              )}
            </div>
            <h1 style={styles.title}>{graph.name}</h1>
            {graph.description && <p style={styles.description}>{graph.description}</p>}
          </div>
          <div style={styles.actions}>
            <button style={styles.actionBtn} onClick={() => onEdit(graph.id)}>
              ✎ Edit
            </button>
            <button
              style={styles.publishBtn}
              onClick={() => setPublishOpen(true)}
              disabled={!canPublish}
              title={canPublish ? "" : "Add at least one node to publish"}
            >
              Publish v{nextVersion}
            </button>
          </div>
        </div>

        <nav style={styles.tabBar}>
          {TABS.map((t) => (
            <button
              key={t.id}
              style={{
                ...styles.tab,
                ...(activeTab === t.id ? styles.tabActive : {}),
                ...(t.disabled ? styles.tabDisabled : {}),
              }}
              onClick={() => !t.disabled && setActiveTab(t.id)}
              disabled={t.disabled}
            >
              {t.label}
              {t.disabled && <span style={styles.soon}> (soon)</span>}
            </button>
          ))}
        </nav>
      </div>

      <div style={styles.content}>
        {activeTab === "overview" && <OverviewTab graph={graph} />}
        {activeTab === "versions" && <VersionsTab graphId={graph.id} />}
      </div>

      <PublishModal
        open={publishOpen}
        graphId={graph.id}
        nextVersion={nextVersion}
        onClose={() => setPublishOpen(false)}
      />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: { background: "#fff", borderBottom: "1px solid #e5e7eb" },
  headerTop: {
    display: "flex",
    alignItems: "flex-start",
    padding: "16px 24px 12px",
    gap: 16,
    maxWidth: 1200,
    margin: "0 auto",
    width: "100%",
    boxSizing: "border-box",
  },
  backBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#2563eb",
    fontWeight: 600,
    fontSize: 14,
    marginTop: 4,
  },
  titleBlock: { flex: 1 },
  pathRow: { display: "flex", alignItems: "center", gap: 8 },
  path: {
    fontFamily: "monospace",
    fontSize: 12,
    color: "#4b5563",
    background: "#f3f4f6",
    padding: "2px 8px",
    borderRadius: 4,
  },
  versionBadge: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    color: "#374151",
    fontSize: 11,
    fontWeight: 700,
    padding: "1px 7px",
    borderRadius: 3,
  },
  title: { margin: "6px 0 3px", fontSize: 22, fontWeight: 700, color: "#111827" },
  description: { margin: 0, color: "#4b5563", fontSize: 13 },
  actions: { display: "flex", gap: 8, flexShrink: 0 },
  actionBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "6px 14px",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 13,
  },
  publishBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "6px 16px",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
  },
  tabBar: {
    display: "flex",
    gap: 2,
    padding: "0 24px",
    maxWidth: 1200,
    margin: "0 auto",
    width: "100%",
    boxSizing: "border-box",
  },
  tab: {
    background: "none",
    border: "none",
    padding: "10px 14px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    color: "#6b7280",
    borderBottom: "2px solid transparent",
  },
  tabActive: {
    color: "#2563eb",
    borderBottom: "2px solid #2563eb",
  },
  tabDisabled: {
    color: "#d1d5db",
    cursor: "not-allowed",
  },
  soon: { fontSize: 10, fontWeight: 400, color: "#9ca3af", marginLeft: 3 },
  content: {
    padding: 24,
    maxWidth: 1200,
    margin: "0 auto",
  },
};
```

- [ ] **Step 2: Commit (will error on missing child imports — fixed in next tasks)**

Don't commit yet. Proceed to Task 14 to fill in `OverviewTab`, `VersionsTab`, `PublishModal` — they need to exist before this compiles.

---

## Task 14: `OverviewTab` component

**Files:**
- Create: `frontend/src/components/GraphDetail/OverviewTab.tsx`

- [ ] **Step 1: Write the component**

Write `frontend/src/components/GraphDetail/OverviewTab.tsx`:
```typescript
import type { Graph } from "../../types";

interface Props {
  graph: Graph;
}

export function OverviewTab({ graph }: Props) {
  const nodeCount = graph.nodes?.length ?? 0;
  const edgeCount = graph.edges?.length ?? 0;
  const hasSchema = Boolean(graph.input_schema && graph.output_schema);

  return (
    <div style={styles.grid}>
      <section style={styles.card}>
        <div style={styles.sectionLabel}>Graph</div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Slug</span>
          <code style={styles.code}>{graph.slug ?? "—"}</code>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Nodes</span>
          <span>{nodeCount}</span>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Edges</span>
          <span>{edgeCount}</span>
        </div>
        <div style={styles.row}>
          <span style={styles.rowLabel}>Retention</span>
          <span>{graph.retention_days} days</span>
        </div>
      </section>

      <section style={styles.card}>
        <div style={styles.sectionLabel}>Publish state</div>
        {graph.latest_version_number ? (
          <>
            <div style={styles.big}>v{graph.latest_version_number}</div>
            <div style={{ color: "#6b7280", fontSize: 12 }}>
              Latest published version
            </div>
          </>
        ) : (
          <div style={styles.emptyState}>
            Draft only — not yet published. Use the <strong>Publish</strong> button above to create v1.
          </div>
        )}
        <div style={styles.row}>
          <span style={styles.rowLabel}>Schemas</span>
          <span style={{ color: hasSchema ? "#16a34a" : "#d97706" }}>
            {hasSchema ? "✓ declared" : "⚠ missing"}
          </span>
        </div>
      </section>

      <section style={{ ...styles.card, gridColumn: "1 / -1" }}>
        <div style={styles.sectionLabel}>Graph structure</div>
        {nodeCount === 0 ? (
          <div style={styles.emptyState}>This graph has no nodes. Click Edit to build it.</div>
        ) : (
          <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
            {graph.nodes.map((n) => (
              <li key={n.id} style={{ fontSize: 13, marginBottom: 3 }}>
                <code style={styles.code}>{n.node_key}</code>
                <span style={{ marginLeft: 6, color: "#6b7280" }}>
                  {n.node_type} · {n.label}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  grid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
  },
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
  row: {
    display: "flex",
    justifyContent: "space-between",
    padding: "5px 0",
    fontSize: 13,
    color: "#111827",
    borderBottom: "1px solid #f3f4f6",
  },
  rowLabel: { color: "#6b7280" },
  code: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#f3f4f6",
    padding: "1px 6px",
    borderRadius: 3,
    color: "#374151",
  },
  big: { fontSize: 32, fontWeight: 800, color: "#2563eb" },
  emptyState: {
    color: "#6b7280",
    fontSize: 13,
    padding: "6px 0",
  },
};
```

- [ ] **Step 2: Don't commit yet — still need VersionsTab + PublishModal**

Proceed to Task 15.

---

## Task 15: `VersionsTab` component

**Files:**
- Create: `frontend/src/components/GraphDetail/VersionsTab.tsx`

- [ ] **Step 1: Write the component**

Write `frontend/src/components/GraphDetail/VersionsTab.tsx`:
```typescript
import { useQuery } from "@tanstack/react-query";
import { listGraphVersions } from "../../api/client";
import type { GraphVersionSummary } from "../../types";

interface Props {
  graphId: string;
}

export function VersionsTab({ graphId }: Props) {
  const { data: versions = [], isLoading } = useQuery<GraphVersionSummary[]>({
    queryKey: ["graph-versions", graphId],
    queryFn: () => listGraphVersions(graphId),
  });

  if (isLoading) return <div>Loading versions…</div>;

  if (versions.length === 0) {
    return (
      <div style={styles.empty}>
        <div style={{ fontSize: 14, color: "#374151", fontWeight: 600, marginBottom: 4 }}>
          No published versions yet
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          The current canvas state is always <code>v(latest+1)</code> draft. Edit the graph and click
          <strong> Publish v1 </strong> above to freeze the first version.
        </div>
      </div>
    );
  }

  return (
    <div style={styles.card}>
      <table style={styles.table}>
        <thead>
          <tr style={styles.headRow}>
            <th style={styles.th}>Version</th>
            <th style={styles.th}>Published</th>
            <th style={styles.th}>Notes</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td style={styles.td}>
                <code style={styles.versionCode}>v{v.version}</code>
              </td>
              <td style={styles.td}>
                {new Date(v.published_at).toLocaleString()}
              </td>
              <td style={styles.td}>{v.notes || <span style={{ color: "#9ca3af" }}>—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  empty: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 24,
    textAlign: "center",
  },
  card: {
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
  td: { padding: "10px 14px", borderBottom: "1px solid #f3f4f6", color: "#111827" },
  versionCode: {
    fontFamily: "monospace",
    fontSize: 12,
    background: "#eff6ff",
    color: "#2563eb",
    padding: "2px 8px",
    borderRadius: 3,
    fontWeight: 700,
  },
};
```

- [ ] **Step 2: Don't commit — still need PublishModal**

Proceed to Task 16.

---

## Task 16: `PublishModal` component

**Files:**
- Create: `frontend/src/components/GraphDetail/PublishModal.tsx`

- [ ] **Step 1: Write the modal**

Write `frontend/src/components/GraphDetail/PublishModal.tsx`:
```typescript
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { publishGraph } from "../../api/client";
import { Modal } from "../shared/Modal";

interface Props {
  open: boolean;
  graphId: string;
  nextVersion: number;
  onClose: () => void;
}

export function PublishModal({ open, graphId, nextVersion, onClose }: Props) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const publishMut = useMutation({
    mutationFn: () => publishGraph(graphId, { notes: notes.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["graph", graphId] });
      qc.invalidateQueries({ queryKey: ["graph-versions", graphId] });
      setNotes("");
      setError(null);
      onClose();
    },
    onError: (err: unknown) => {
      const resp = (err as { response?: { data?: { error?: string; detail?: string } } }).response;
      setError(resp?.data?.error ?? resp?.data?.detail ?? "Publish failed");
    },
  });

  return (
    <Modal
      open={open}
      title={`Publish v${nextVersion}`}
      onClose={onClose}
      locked={publishMut.isPending}
    >
      <div style={{ fontSize: 13, marginBottom: 12, color: "#374151" }}>
        This will freeze the current draft as <strong>v{nextVersion}</strong>. The version is
        immutable — you won't be able to change it later. Future edits will go into a new draft.
      </div>

      <label style={styles.label}>Release notes (optional)</label>
      <textarea
        style={styles.textarea}
        placeholder="What changed in this version?"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        disabled={publishMut.isPending}
      />

      {error && (
        <div style={styles.error}>{error}</div>
      )}

      <div style={styles.actions}>
        <button
          style={styles.cancelBtn}
          onClick={onClose}
          disabled={publishMut.isPending}
        >
          Cancel
        </button>
        <button
          style={styles.publishBtn}
          onClick={() => publishMut.mutate()}
          disabled={publishMut.isPending}
        >
          {publishMut.isPending ? "Publishing…" : `Publish v${nextVersion}`}
        </button>
      </div>
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  label: {
    display: "block",
    fontSize: 11,
    fontWeight: 600,
    color: "#374151",
    marginBottom: 4,
  },
  textarea: {
    width: "100%",
    minHeight: 80,
    border: "1px solid #d1d5db",
    borderRadius: 5,
    padding: "7px 10px",
    fontSize: 13,
    fontFamily: "system-ui, sans-serif",
    boxSizing: "border-box",
    resize: "vertical",
  },
  error: {
    background: "#fef2f2",
    border: "1px solid #fca5a5",
    color: "#b91c1c",
    borderRadius: 5,
    padding: "8px 12px",
    fontSize: 12,
    marginTop: 10,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
    marginTop: 14,
    borderTop: "1px solid #e5e7eb",
    paddingTop: 14,
  },
  cancelBtn: {
    background: "#f3f4f6",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    padding: "8px 16px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  },
  publishBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 20px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
  },
};
```

- [ ] **Step 2: Type-check the whole GraphDetail flow**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0. If there are errors about `getGraph` missing, confirm it exists in `api/client.ts` (it should, from the existing code).

- [ ] **Step 3: Commit the GraphDetail stack**

```bash
git add frontend/src/components/GraphDetail/
git commit -m "feat(frontend): GraphDetail shell, Overview, Versions, PublishModal"
```

---

## Task 17: Route graph clicks through `GraphDetail` in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/GraphEditor/index.tsx` (back button target)

- [ ] **Step 1: Update App.tsx state model**

Open `frontend/src/App.tsx`. Replace the `openGraphId` single-state with two fields tracking "which graph detail is open" and "am I in the editor":
```typescript
type View = "graphs" | "agents" | "mcp-servers";

export default function App() {
  const [view, setView] = useState<View>("graphs");
  const [detailGraphId, setDetailGraphId] = useState<string | null>(null);
  const [editorGraphId, setEditorGraphId] = useState<string | null>(null);

  const openGraphDetail = (id: string) => {
    setDetailGraphId(id);
    setEditorGraphId(null);
    setView("graphs");
  };

  const openGraphEditor = (id: string) => {
    setEditorGraphId(id);
  };

  const backFromEditor = () => {
    setEditorGraphId(null);
    // detailGraphId stays set → we return to the detail page
  };

  const backFromDetail = () => {
    setDetailGraphId(null);
  };

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ fontFamily: "system-ui, sans-serif", background: "#f9fafb", minHeight: "100vh" }}>
        {editorGraphId ? (
          <GraphEditor graphId={editorGraphId} onBack={backFromEditor} />
        ) : detailGraphId ? (
          <GraphDetail
            graphId={detailGraphId}
            onBack={backFromDetail}
            onEdit={openGraphEditor}
          />
        ) : (
          <>
            <Header view={view} onChange={setView} />
            {view === "graphs" && <GraphList onOpen={openGraphDetail} />}
            {view === "agents" && <AgentList onOpenGraph={openGraphDetail} />}
            {view === "mcp-servers" && <MCPServerList onOpenGraph={openGraphDetail} />}
          </>
        )}
      </div>
    </QueryClientProvider>
  );
}
```

Add the import:
```typescript
import { GraphDetail } from "./components/GraphDetail";
```

- [ ] **Step 2: Update Header to handle navigation correctly**

If `Header` is defined in the same file (as in the current code), no changes needed — it still takes `view` and `onChange`.

- [ ] **Step 3: Verify GraphEditor's back button still lands correctly**

The existing `onBack` prop is already used for "return to list" — now it returns to `GraphDetail` implicitly because our App state only clears `editorGraphId`, keeping `detailGraphId` set. Verify this by reading `frontend/src/components/GraphEditor/index.tsx` briefly — if the back button label says "Graphs", consider changing it to "← Back" to be accurate in both contexts.

Open `frontend/src/components/GraphEditor/index.tsx` and find the back button:
```tsx
<button style={styles.backBtn} onClick={onBack}>
  ← Back
</button>
```
(change the label from whatever it was — probably `← Graphs` — to `← Back` for context-independence).

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/GraphEditor/index.tsx
git commit -m "feat(frontend): route graph clicks through GraphDetail page"
```

---

## Task 18: GraphList shows slug on cards

**Files:**
- Modify: `frontend/src/components/GraphList/index.tsx`

- [ ] **Step 1: Display the slug alongside the name**

In the graph card body, below the title row, render the slug if it exists:
```tsx
<div style={styles.cardBody}>
  <div style={styles.cardTitle}>{g.name}</div>
  {g.slug && (
    <code style={styles.slug}>acme/{g.slug}</code>
  )}
  {g.description && <div style={styles.cardDesc}>{g.description}</div>}
  <div style={styles.cardMeta}>
    {g.latest_version_number
      ? <>v{g.latest_version_number} (latest)</>
      : <>draft only</>}
    {" · "}
    {new Date(g.updated_at).toLocaleDateString()}
  </div>
</div>
```

Add to the local `styles` object:
```typescript
slug: {
  display: "inline-block",
  fontFamily: "monospace",
  fontSize: 11,
  color: "#6b7280",
  background: "#f3f4f6",
  padding: "1px 6px",
  borderRadius: 3,
  marginTop: 3,
  marginBottom: 3,
},
```

(Replace the `v{g.version}` / `"parent_graph_id && cloned"` logic with the new version-number-based display. Keep the `cloned` marker if it was previously shown.)

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphList/index.tsx
git commit -m "feat(frontend): graph list shows slug and latest version"
```

---

## Task 19: End-to-end verification

**Files:** none — manual test of the full integrated behavior.

- [ ] **Step 1: Rebuild and start**

```bash
docker compose down
docker compose up --build
```

Wait for all services to report healthy.

- [ ] **Step 2: Verify seed auto-publish**

```bash
curl -s http://localhost:8000/api/v1/graphs/00000000-0000-0000-0000-000000000020/versions | jq
```

Expected: one version object with `"version": 1, "notes": "Initial seed publish"`.

- [ ] **Step 3: Walk the frontend flow**

Open http://localhost:5173 in a browser.
- Click **Graphs** tab, confirm the seed graph shows with `acme/change-risk-analyzer` slug and `v1 (latest)` label.
- Click the graph card. Expect: `GraphDetail` page loads with header showing `acme / change-risk-analyzer`, description, and `v1` badge.
- Tab bar shows: Overview (active) | API Docs (soon) | Versions | Keys (soon) | Runs (soon) | Test (soon).
- **Overview tab**: confirm node/edge counts, schemas status (✓ declared), latest version v1.
- **Versions tab**: click it. One row: `v1`, the publish timestamp, `Initial seed publish`.
- Click **Edit** button. GraphEditor opens at the canvas. Click the new **Schemas** toolbar button.
- Schemas drawer opens with Input/Output tabs. Confirm input schema shows `title`, `description`, `affected_services`, `proposed_window` rows. Switch to JSON mode, confirm JSON is valid and matches what's displayed.
- Close drawer. Click **← Back** — should land back at the GraphDetail page, NOT the graph list.
- Click back arrow (`← Graphs`) on GraphDetail — should land at the graph list.

- [ ] **Step 4: Publish a v2**

- From GraphList, click the graph card to open `GraphDetail`.
- Click **Edit** to open the canvas.
- Make a trivial change (e.g. reposition a node).
- Save the graph.
- Click **← Back** to return to `GraphDetail`.
- The Publish button should now say **Publish v2**. Click it.
- Enter release notes: "Moved a node". Click **Publish v2**.
- Expect: modal closes, the version badge in the header updates (refetched by query invalidation).
- Click **Versions** tab. Expect: two rows — v2 first, then v1.

- [ ] **Step 5: Try to publish an invalid graph**

- Delete the seed MCP server from the MCP Servers tab (use the delete flow, confirm through the usages warning checkbox).
- Go back to the graph's `GraphDetail`. Click Publish.
- Expect: modal shows error "Node 'fetch_deps': mcp server 00000000-0000-0000-0000-000000000010 not found. Remove or repoint the reference before publishing."
- Cancel, re-register the MCP server (or revert via `docker compose restart backend` to re-seed), and try publish again — should succeed.

- [ ] **Step 6: Run backend tests in the container**

```bash
docker compose exec backend pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit the checklist completion (no code, just a checkpoint)**

If any issues surfaced during verification and required code changes, commit them separately. Otherwise, Plan A is complete.

```bash
git log --oneline -20
```

Expected: all task commits land in sequence with clean messages.

---

## Acceptance checklist (spec mapping)

Run through this before declaring Plan A done. Each item maps to a requirement in the parent spec.

- [ ] **§4 Versioning** — A graph has a draft (canvas) and one or more published `graph_versions` rows. ✓ Tasks 2, 3, 6, 9
- [ ] **§4 Contract** — Graphs carry `input_schema` and `output_schema`. Editable via the Schemas drawer. ✓ Tasks 3, 4, 8, 11, 12
- [ ] **§5.1 `graph_versions` table** — Immutable, 1-indexed, unique per graph. ✓ Tasks 2, 3, 6
- [ ] **§5.2 Graph columns** — `slug`, schemas, `latest_published_version_id`, `retention_days`, `test_examples`. ✓ Tasks 2, 3
- [ ] **§5.2 Org.slug** — Column added and backfilled. ✓ Tasks 2, 3, 9
- [ ] **§5.3 Migration** — Backfills existing seeded org and graph slugs before enforcing unique constraints. ✓ Task 2
- [ ] **§6.3 Management endpoints** — `PATCH /graphs/{id}`, `POST /graphs/{id}/publish`, `GET /graphs/{id}/versions`, `GET /graphs/{id}/versions/{v}`. ✓ Tasks 6, 7, 8
- [ ] **§8.1 Navigation** — Graph click now opens `GraphDetail`, not `GraphEditor`. ✓ Task 17
- [ ] **§8.2 GraphDetail shell** — Header with name, slug, version badge, Edit, Publish buttons; tab bar with all six tabs (four as placeholders). ✓ Tasks 13, 17
- [ ] **§8.3 Overview tab** — Summary card, stats, schemas status, latest version. ✓ Task 14
- [ ] **§8.3 Versions tab** — Table of published versions, newest first. ✓ Task 15
- [ ] **§8.4 JSON Schema editor** — Visual + JSON modes, one level of nesting, read-only mode. ✓ Task 11
- [ ] **§9 Publish validation** — Empty draft rejected, dangling refs rejected, missing schemas warn. ✓ Tasks 5, 6
- [ ] **Seed integrity** — Seed auto-publishes v1 on fresh DB; idempotent on re-run. ✓ Task 9
- [ ] **Backend test coverage** — Publish endpoint, versions endpoints, PATCH graph, publish validation all covered. ✓ Tasks 5, 6, 7, 8
- [ ] **Frontend type-check passes** — `npx tsc --noEmit` exits 0. ✓ Tasks 10–18

---

## What Plan A does NOT deliver (intentional — deferred to later plans)

- **API Docs tab content** — tab exists but is marked "(soon)" and disabled. Plan B fills it.
- **Test tab** — tab exists but is disabled. Plan B fills it.
- **Runs tab** — tab exists but is disabled. Plan B fills it.
- **Keys tab** — tab exists but is disabled. Plan C fills it.
- **Public `/v1/run/...` endpoints** — Plan C.
- **Async jobs + webhooks** — Plan D.
- **Runs persistence** — Plan B (the `runs`/`run_steps` tables don't exist yet).
- **"Generate schema from last run"** button — depends on runs persistence; Plan B.
- **Per-version viewing on the other tabs** — the header version dropdown is future polish; Plan B's API Docs tab introduces it.
- **Graph definition diff on the Versions tab** — deferred to a later polish pass; v1 shows only the table.

---

*End of Plan A. After all tasks complete and the acceptance checklist is green, the next plan (Plan B — Runs persistence + API Docs / Test / Runs tabs) can begin from this commit.*
