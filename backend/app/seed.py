"""
Seed the database with a dev org, dev user, mock services, and a demo graph.

Idempotency contract
--------------------
Every seeded entity has a fixed well-known UUID.  On each startup the seed:
  - INSERTs the entity if it doesn't exist yet.
  - UPDATEs it in-place if the desired state (defined here) differs from what's
    stored — so a code change to the seed definition is reflected on next restart
    without a volume wipe.
  - Leaves it alone (UNCHANGED) if the DB already matches the desired state.

Only the canonical seeded entities (identified by their fixed UUIDs) are managed
here. User-created graphs, agents, and MCP servers are never touched.

Graph node/edge replacement
----------------------------
When the seed graph definition changes, all graph_nodes and graph_edges rows for
that graph are deleted and recreated.  This is safe because the seeded graph is
always canonical; user forks (different graph_id) are untouched.

Startup log
-----------
  {"event": "seed_complete", "inserted": N, "updated": N, "unchanged": N}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from typing import TypedDict

from sqlalchemy import delete

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.db import AsyncSessionLocal
from app.models.agent import Agent
from app.models.graph import Graph, GraphEdge, GraphNode
from app.models.mcp_server import MCPServer
from app.models.user import Org, TenantGroupMapping, User

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed seed identifiers
# ---------------------------------------------------------------------------

SEED_MCP_SERVER_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
SEED_A2A_AGENT_ID  = uuid.UUID("00000000-0000-0000-0000-000000000011")
SEED_GRAPH_ID      = uuid.UUID("00000000-0000-0000-0000-000000000020")
SEED_API_KEY_ID    = uuid.UUID("00000000-0000-0000-0000-000000000030")

# Second workspace + AD group mappings — demonstrates AD-group-driven
# multi-tenancy out of the box. The dev fallback identity belongs to
# 'agent-platform-admins' and 'agent-platform-users', so it owns the Demo
# workspace but cannot see ML Research (mapped to 'ml-research-team').
SEED_ORG2_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
SEED_MAPPING_DEMO_OWNER_ID  = uuid.UUID("00000000-0000-0000-0000-000000000040")
SEED_MAPPING_DEMO_EDITOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000041")
SEED_MAPPING_ML_OWNER_ID    = uuid.UUID("00000000-0000-0000-0000-000000000042")

SEED_GROUP_MAPPINGS = [
    {"id": SEED_MAPPING_DEMO_OWNER_ID,  "org_id": DEV_ORG_ID,   "ad_group": "agent-platform-admins", "role": "owner"},
    {"id": SEED_MAPPING_DEMO_EDITOR_ID, "org_id": DEV_ORG_ID,   "ad_group": "agent-platform-users",  "role": "editor"},
    {"id": SEED_MAPPING_ML_OWNER_ID,    "org_id": SEED_ORG2_ID, "ad_group": "ml-research-team",      "role": "owner"},
]
# The plaintext for the seed key is deterministic so curl examples in docs
# and the readme can reference it. This is ONLY safe because it's a local-dev
# key seeded in DEBUG mode. Production deployments never run the seed.
SEED_API_KEY_PLAINTEXT = "ap_live_demoseedkey0000000000000000000000"

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_MCP_SCRIPT = os.path.join(_HERE, "seed_services", "mock_mcp_server.py")
SEED_A2A_URL = os.environ.get("SEED_AGENT_URL", "http://seed-agent:8001")

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


# ---------------------------------------------------------------------------
# Stats counter
# ---------------------------------------------------------------------------

class SeedStats(TypedDict):
    inserted: int
    updated: int
    unchanged: int


def _new_stats() -> SeedStats:
    return {"inserted": 0, "updated": 0, "unchanged": 0}


# ---------------------------------------------------------------------------
# Canonical comparison helper
# ---------------------------------------------------------------------------

def _canon(obj: object) -> str:
    """Stable JSON string for equality comparison (handles nested dicts/lists)."""
    return json.dumps(obj, sort_keys=True, default=str)


def _fields_changed(row: object, desired: dict) -> bool:
    """Return True if any field in desired differs from the current ORM row value."""
    return any(getattr(row, k) != v for k, v in desired.items())


def _apply_fields(row: object, desired: dict) -> None:
    for k, v in desired.items():
        setattr(row, k, v)


# ---------------------------------------------------------------------------
# Desired seed state — single source of truth
# Changing anything here → reflected on next backend restart
# ---------------------------------------------------------------------------

def _desired_mcp_server() -> dict:
    return {
        "name":        "Dependency Lookup (demo, stdio)",
        "description": (
            "Returns upstream/downstream dependencies for a service. "
            "Used to assess blast radius of proposed changes."
        ),
        "transport":  "stdio",
        "command":    sys.executable,
        "args":       [SEED_MCP_SCRIPT],
        "env_vars":   None,
        "visibility": "catalog",
        "tags":       ["demo", "dependencies", "ops"],
    }


def _desired_agent() -> dict:
    return {
        "name":          "Change Risk Narrative Assessor (demo)",
        "description":   (
            "Produces detailed narrative risk assessments for high-risk changes. "
            "Analyzes impact, rollback complexity, and recommends approval conditions."
        ),
        "agent_type":    "http",
        "url":           SEED_A2A_URL,
        "agent_card_url": f"{SEED_A2A_URL}/.well-known/agent.json",
        "visibility":    "catalog",
        "tags":          ["demo", "risk-assessment", "a2a"],
    }


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


def _desired_nodes() -> list[dict]:
    """Node definitions — changing any field here triggers a graph update on next restart."""
    return [
        {
            "node_key":   "classify",
            "node_type":  "llm",
            "label":      "Classify Risk",
            "position_x": 100,
            "position_y": 200,
            "ref_id":     None,
            "config_json": {
                "model": "claude-sonnet-4-6",
                "system_prompt": (
                    "You are a change request risk classifier for a software platform. "
                    "Analyze the change request and classify its risk level. "
                    "Be conservative: when in doubt, escalate.\n\n"
                    "You must call the classify_risk tool with your assessment."
                ),
                "tools": [
                    {
                        "name": "classify_risk",
                        "description": "Classify the risk level of a change request",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "risk_level": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Overall risk level",
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "One-paragraph explanation of the classification",
                                },
                                "key_concerns": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of specific risk factors identified",
                                },
                                "confidence": {
                                    "type": "number",
                                    "description": "Confidence score 0.0–1.0",
                                },
                            },
                            "required": ["risk_level", "reasoning", "key_concerns", "confidence"],
                        },
                    }
                ],
                "context_key": "classification",
            },
        },
        {
            "node_key":   "route_risk",
            "node_type":  "router",
            "label":      "Route by Risk",
            "position_x": 400,
            "position_y": 200,
            "ref_id":     None,
            "config_json": {
                "source": "context.classification.risk_level",
                "routes": {
                    "high":   "assess_narrative",
                    "medium": "fetch_deps",
                    "low":    "summarize",
                },
                "default": "summarize",
            },
        },
        {
            "node_key":   "assess_narrative",
            "node_type":  "a2a",
            "label":      "Narrative Assessment",
            "position_x": 700,
            "position_y": 80,
            "ref_id":     str(SEED_A2A_AGENT_ID),
            "config_json": {
                "agent_id":    str(SEED_A2A_AGENT_ID),
                "context_key": "narrative",
            },
        },
        {
            "node_key":   "fetch_deps",
            "node_type":  "mcp_tool",
            "label":      "Fetch Dependencies",
            "position_x": 1000,
            "position_y": 200,
            "ref_id":     str(SEED_MCP_SERVER_ID),
            "config_json": {
                "mcp_server_id": str(SEED_MCP_SERVER_ID),
                "tool_name":     "lookup_dependencies",
                "arguments":     {"service_name": "{{input.affected_services}}"},
                "output_key":    "dependencies",
            },
        },
        {
            "node_key":   "summarize",
            "node_type":  "llm",
            "label":      "Generate Report",
            "position_x": 1300,
            "position_y": 200,
            "ref_id":     None,
            "config_json": {
                "model": "claude-sonnet-4-6",
                "system_prompt": (
                    "You are a change management coordinator generating a final risk report. "
                    "You will receive a JSON object containing:\n"
                    "  - input: the original change request\n"
                    "  - context.classification: the risk classification\n"
                    "  - context.narrative: (high-risk only) narrative assessment from a specialist agent\n"
                    "  - context.dependencies: (medium/high only) service dependency data\n\n"
                    "Generate a concise final report in this exact markdown format:\n\n"
                    "## Change Request Risk Report\n\n"
                    "**Title:** <title>\n"
                    "**Risk Level:** <HIGH|MEDIUM|LOW> (confidence: <pct>%)\n"
                    "**Proposed Window:** <window>\n\n"
                    "### Summary\n"
                    "<2-3 sentence summary>\n\n"
                    "### Key Concerns\n"
                    "<bulleted list>\n\n"
                    "### Dependency Impact\n"
                    "<only if dependency data present, otherwise omit this section>\n\n"
                    "### Specialist Assessment\n"
                    "<only if narrative present, otherwise omit this section>\n\n"
                    "### Recommendation\n"
                    "<APPROVE / APPROVE WITH CONDITIONS / ESCALATE TO CAB> — one sentence rationale"
                ),
                "parse_json":      False,
                "include_context": True,
                "context_key":     "report",
            },
        },
    ]


def _desired_edges() -> list[dict]:
    return [
        {"source_node_key": "__start__",       "target_node_key": "classify",        "condition": None},
        {"source_node_key": "classify",         "target_node_key": "route_risk",      "condition": None},
        {"source_node_key": "route_risk",       "target_node_key": "assess_narrative","condition": "high"},
        {"source_node_key": "route_risk",       "target_node_key": "fetch_deps",      "condition": "medium"},
        {"source_node_key": "route_risk",       "target_node_key": "summarize",       "condition": "low"},
        {"source_node_key": "assess_narrative", "target_node_key": "fetch_deps",      "condition": None},
        {"source_node_key": "fetch_deps",       "target_node_key": "summarize",       "condition": None},
        {"source_node_key": "summarize",        "target_node_key": "__end__",         "condition": None},
    ]


def _build_definition(nodes_data: list[dict], edges_data: list[dict]) -> dict:
    """Build the denormalized definition_json consumed by the execution engine."""
    return {
        "nodes": [
            {
                "key":    n["node_key"],
                "type":   n["node_type"],
                "label":  n["label"],
                "ref_id": n.get("ref_id"),
                "config": n.get("config_json") or {},
            }
            for n in nodes_data
        ],
        "edges": [
            {
                "from":      e["source_node_key"],
                "to":        e["target_node_key"],
                "condition": e["condition"],
            }
            for e in edges_data
        ],
    }


# ---------------------------------------------------------------------------
# Per-entity upsert helpers
# ---------------------------------------------------------------------------

async def _upsert_org(db, stats: SeedStats) -> None:
    desired_orgs = [
        {
            "id": DEV_ORG_ID,
            "name": "Demo Workspace",
            "slug": "demo",
            "description": "Default workspace for the seeded demo graph and registries.",
        },
        {
            "id": SEED_ORG2_ID,
            "name": "ML Research",
            "slug": "ml-research",
            "description": "Second seeded workspace — demonstrates AD-group tenant isolation.",
        },
    ]
    for desired in desired_orgs:
        org = await db.get(Org, desired["id"])
        fields = {k: v for k, v in desired.items() if k != "id"}
        if not org:
            db.add(Org(**desired))
            stats["inserted"] += 1
        elif _fields_changed(org, fields):
            _apply_fields(org, fields)
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1


async def _upsert_group_mappings(db, stats: SeedStats) -> None:
    """AD group → workspace/role mappings (membership source of truth)."""
    for desired in SEED_GROUP_MAPPINGS:
        mapping = await db.get(TenantGroupMapping, desired["id"])
        fields = {k: v for k, v in desired.items() if k != "id"}
        if not mapping:
            db.add(TenantGroupMapping(created_by=DEV_USER_ID, **desired))
            stats["inserted"] += 1
        elif _fields_changed(mapping, fields):
            _apply_fields(mapping, fields)
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1


async def _upsert_user(db, stats: SeedStats) -> None:
    user = await db.get(User, DEV_USER_ID)
    if not user:
        db.add(User(
            id=DEV_USER_ID,
            email="dev@example.com",
            display_name="Dev User",
            ad_groups=["agent-platform-admins", "agent-platform-users"],
            org_id=DEV_ORG_ID,
        ))
        stats["inserted"] += 1
    else:
        stats["unchanged"] += 1


async def _upsert_mcp_server(db, stats: SeedStats) -> None:
    desired = _desired_mcp_server()
    mcp = await db.get(MCPServer, SEED_MCP_SERVER_ID)
    if not mcp:
        mcp = MCPServer(id=SEED_MCP_SERVER_ID, created_by=DEV_USER_ID, org_id=DEV_ORG_ID, **desired)
        db.add(mcp)
        await db.flush()
        await _probe_mcp_tools(mcp)
        stats["inserted"] += 1
    else:
        changed = _fields_changed(mcp, desired)
        if changed:
            _apply_fields(mcp, desired)
        # Re-probe whenever config changed (e.g. new script) or tools were never discovered
        if changed or mcp.tools_json is None:
            await _probe_mcp_tools(mcp)
        stats["updated" if changed else "unchanged"] += 1


async def _probe_mcp_tools(mcp: MCPServer) -> None:
    """Best-effort: discover and cache tool list from the MCP server."""
    try:
        from app.engine.mcp_client import list_tools
        tools = await list_tools(
            transport=mcp.transport,
            command=mcp.command,
            args=mcp.args,
            env_vars=mcp.env_vars,
        )
        mcp.tools_json = tools
        log.info("mcp_tools_probed", extra={"server": mcp.name, "count": len(tools)})
    except Exception as exc:
        log.warning("mcp_tool_probe_failed", extra={"server": mcp.name, "error": str(exc)})


async def _upsert_agent(db, stats: SeedStats) -> None:
    desired = _desired_agent()
    agent = await db.get(Agent, SEED_A2A_AGENT_ID)
    if not agent:
        agent = Agent(id=SEED_A2A_AGENT_ID, created_by=DEV_USER_ID, org_id=DEV_ORG_ID, **desired)
        db.add(agent)
        await db.flush()
        await _probe_agent_card(agent)
        stats["inserted"] += 1
    else:
        changed = _fields_changed(agent, desired)
        if changed:
            _apply_fields(agent, desired)
        if agent.agent_card_json is None:
            await _probe_agent_card(agent)
            changed = True
        stats["updated" if changed else "unchanged"] += 1


async def _probe_agent_card(agent: Agent) -> None:
    """Best-effort: fetch and cache the A2A agent card."""
    try:
        from app.a2a.card import try_fetch_agent_card
        card = await try_fetch_agent_card(agent.url or "")
        if card:
            agent.agent_card_json = card
            log.info("agent_card_probed", extra={"agent": agent.name})
    except Exception as exc:
        log.warning("agent_card_probe_failed", extra={"agent": agent.name, "error": str(exc)})


async def _ensure_catalog_published_at(db) -> None:
    """Stamp published_at on the catalog-visible seed entries (kept out of the
    desired-state dicts because the timestamp is dynamic)."""
    from datetime import datetime, timezone

    for model, row_id in ((MCPServer, SEED_MCP_SERVER_ID), (Agent, SEED_A2A_AGENT_ID)):
        row = await db.get(model, row_id)
        if row and row.visibility == "catalog" and row.published_at is None:
            row.published_at = datetime.now(timezone.utc)


async def _upsert_graph(db, stats: SeedStats) -> None:
    nodes_data = _desired_nodes()
    edges_data = _desired_edges()
    desired_definition = _build_definition(nodes_data, edges_data)
    desired_meta = _desired_graph_meta()

    graph = await db.get(Graph, SEED_GRAPH_ID)
    if not graph:
        graph = Graph(
            id=SEED_GRAPH_ID,
            version=1,
            parent_graph_id=None,
            created_by=DEV_USER_ID,
            org_id=DEV_ORG_ID,
            definition_json=desired_definition,
            **desired_meta,
        )
        db.add(graph)
        await db.flush()
        await _replace_nodes_edges(db, graph.id, nodes_data, edges_data)
        stats["inserted"] += 1
    else:
        meta_changed = _fields_changed(graph, desired_meta)
        defn_changed = _canon(graph.definition_json) != _canon(desired_definition)

        if meta_changed:
            _apply_fields(graph, desired_meta)
        if defn_changed:
            await _replace_nodes_edges(db, graph.id, nodes_data, edges_data)
            graph.definition_json = desired_definition

        if meta_changed or defn_changed:
            log.info(
                "seed_graph_updated",
                extra={
                    "meta_changed": meta_changed,
                    "definition_changed": defn_changed,
                },
            )
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1


async def _ensure_seed_graph_published(db, stats: SeedStats) -> None:
    """
    Ensure the seed graph has at least one published version. Idempotent:
    if a version already exists, this is a no-op.
    """
    from sqlalchemy import select
    from app.models.graph import GraphVersion

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


async def _upsert_api_key(db, stats: SeedStats) -> None:
    from app.models.api_key import ApiKey
    from app.services.api_keys import hash_key, split_prefix

    key = await db.get(ApiKey, SEED_API_KEY_ID)
    if not key:
        db.add(ApiKey(
            id=SEED_API_KEY_ID,
            org_id=DEV_ORG_ID,
            name="Demo dev key",
            key_prefix=split_prefix(SEED_API_KEY_PLAINTEXT),
            key_hash=hash_key(SEED_API_KEY_PLAINTEXT),
            key_last4=SEED_API_KEY_PLAINTEXT[-4:],
            scopes=["*"],
            created_by=DEV_USER_ID,
        ))
        stats["inserted"] += 1
        log.info("seeded_demo_api_key")
    else:
        # Don't re-hash or mutate the existing key — it's already correct
        stats["unchanged"] += 1


async def _replace_nodes_edges(
    db,
    graph_id: uuid.UUID,
    nodes_data: list[dict],
    edges_data: list[dict],
) -> None:
    """
    Atomically replace all nodes and edges for this graph with the desired state.
    Uses raw DELETE so we don't need to load the relationship collections.
    """
    await db.execute(delete(GraphEdge).where(GraphEdge.graph_id == graph_id))
    await db.execute(delete(GraphNode).where(GraphNode.graph_id == graph_id))
    await db.flush()

    for nd in nodes_data:
        ref_str = nd.get("ref_id")
        db.add(GraphNode(
            graph_id=graph_id,
            node_key=nd["node_key"],
            node_type=nd["node_type"],
            label=nd["label"],
            position_x=nd.get("position_x", 0.0),
            position_y=nd.get("position_y", 0.0),
            ref_id=uuid.UUID(ref_str) if ref_str else None,
            config_json=nd.get("config_json") or {},
        ))

    for ed in edges_data:
        db.add(GraphEdge(
            graph_id=graph_id,
            source_node_key=ed["source_node_key"],
            target_node_key=ed["target_node_key"],
            condition=ed.get("condition"),
        ))

    await db.flush()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def seed() -> None:
    """
    Run the seed against the current DB.  Safe to call on every startup.
    Logs a summary: seed_complete {inserted, updated, unchanged}.
    """
    stats = _new_stats()

    async with AsyncSessionLocal() as db:
        await _upsert_org(db, stats)
        await db.flush()

        await _upsert_user(db, stats)
        await db.flush()

        await _upsert_group_mappings(db, stats)
        await db.flush()

        await _upsert_mcp_server(db, stats)
        await db.flush()

        await _upsert_agent(db, stats)
        await db.flush()

        await _ensure_catalog_published_at(db)
        await db.flush()

        await _upsert_graph(db, stats)
        await _ensure_seed_graph_published(db, stats)
        await _upsert_api_key(db, stats)

        await db.commit()

    log.info(
        "seed_complete",
        extra={
            "inserted":  stats["inserted"],
            "updated":   stats["updated"],
            "unchanged": stats["unchanged"],
        },
    )


# ---------------------------------------------------------------------------
# CLI entry point (runs migrations first, then seed)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import threading
    from app.config import settings
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)

    def _migrate() -> None:
        from alembic import command as alembic_command
        from alembic.config import Config
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = Config(os.path.join(backend_dir, "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", settings.database_url)
        alembic_command.upgrade(cfg, "head")

    t = threading.Thread(target=_migrate)
    t.start()
    t.join()

    asyncio.run(seed())
