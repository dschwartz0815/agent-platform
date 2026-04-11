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
