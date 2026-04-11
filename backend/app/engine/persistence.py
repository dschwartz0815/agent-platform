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
