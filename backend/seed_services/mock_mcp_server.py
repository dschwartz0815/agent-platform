"""
Mock MCP Server — Dependency Lookup

A stdio MCP server that provides:
  - lookup_dependencies(service_name: str) -> list of upstream/downstream deps

Responses are deterministic (no external calls) so the demo works anywhere.

Run standalone for testing:
    python backend/seed_services/mock_mcp_server.py

In production seed, this is registered with transport='stdio' and invoked per-call
by the platform's MCP client.
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fake dependency graph — realistic-looking service mesh
# ---------------------------------------------------------------------------

_DEPENDENCY_MAP: dict[str, dict] = {
    "payments-service": {
        "upstream": ["api-gateway", "auth-service"],
        "downstream": ["ledger-service", "fraud-detection", "notification-service"],
        "databases": ["payments-postgres", "payments-redis"],
        "criticality": "high",
        "sla_minutes": 99.99,
    },
    "auth-service": {
        "upstream": ["api-gateway"],
        "downstream": ["user-service", "session-store"],
        "databases": ["auth-postgres", "redis-sessions"],
        "criticality": "high",
        "sla_minutes": 99.99,
    },
    "api-gateway": {
        "upstream": [],
        "downstream": [
            "auth-service", "payments-service", "orders-service",
            "inventory-service", "notification-service",
        ],
        "databases": [],
        "criticality": "critical",
        "sla_minutes": 99.999,
    },
    "orders-service": {
        "upstream": ["api-gateway", "auth-service"],
        "downstream": ["inventory-service", "payments-service", "notification-service"],
        "databases": ["orders-postgres"],
        "criticality": "high",
        "sla_minutes": 99.9,
    },
    "inventory-service": {
        "upstream": ["orders-service", "api-gateway"],
        "downstream": ["warehouse-service"],
        "databases": ["inventory-postgres", "inventory-cache"],
        "criticality": "medium",
        "sla_minutes": 99.5,
    },
    "notification-service": {
        "upstream": [
            "payments-service", "orders-service", "auth-service"
        ],
        "downstream": [],
        "databases": ["notifications-queue"],
        "criticality": "low",
        "sla_minutes": 99.0,
    },
    "user-service": {
        "upstream": ["auth-service", "api-gateway"],
        "downstream": ["notification-service"],
        "databases": ["users-postgres"],
        "criticality": "medium",
        "sla_minutes": 99.5,
    },
    "ledger-service": {
        "upstream": ["payments-service"],
        "downstream": ["reporting-service"],
        "databases": ["ledger-postgres"],
        "criticality": "high",
        "sla_minutes": 99.99,
    },
}

_DEFAULT_DEPS = {
    "upstream": [],
    "downstream": [],
    "databases": [],
    "criticality": "unknown",
    "sla_minutes": 99.0,
}


# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

server = Server("mock-dependency-lookup")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="lookup_dependencies",
            description=(
                "Look up the upstream and downstream dependencies for a service. "
                "Returns a structured dependency map including databases, criticality "
                "rating, and SLA targets. Used to assess blast radius of changes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Name of the service to look up. "
                            "E.g. 'payments-service', 'auth-service', 'api-gateway'."
                        ),
                    }
                },
                "required": ["service_name"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "lookup_dependencies":
        raise ValueError(f"Unknown tool: {name!r}")

    raw = arguments.get("service_name", "")
    # Accept both a single service name string and a list of names
    if isinstance(raw, list):
        service_names = [str(s).lower().strip() for s in raw if s]
    else:
        service_names = [str(raw).lower().strip()] if raw else []

    if not service_names:
        service_names = ["unknown"]

    results = []
    for service_name in service_names:
        normalized = service_name
        for suffix in ("-service", "-svc", "service", "svc"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)] + "-service"
                break

        deps = _DEPENDENCY_MAP.get(normalized) or _DEPENDENCY_MAP.get(service_name)
        if deps:
            results.append({
                "service": normalized or service_name,
                "found": True,
                **deps,
            })
        else:
            results.append({
                "service": service_name,
                "found": False,
                "upstream": [],
                "downstream": [],
                "databases": [],
                "criticality": "unknown",
                "sla_minutes": None,
                "note": f"Service '{service_name}' not found in dependency registry. Treat as isolated.",
            })

    # Return single dict for one service, list for multiple
    result = results[0] if len(results) == 1 else results
    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
