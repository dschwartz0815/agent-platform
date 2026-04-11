#!/usr/bin/env python3
"""
Demo MCP server (stdio transport) for the seed graph.

Exposes two tools:
  get_similar_changes(description: str) → list of historical similar changes
  calculate_risk_score(risk_level: str, affected_systems: list) → numeric score

Run standalone to verify:
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | python risk_analyzer.py
"""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("risk-analyzer")

HISTORICAL_CHANGES = [
    {
        "id": "CR-1042",
        "description": "Database schema migration for user table",
        "outcome": "rollback required",
        "risk_level": "high",
        "affected_systems": ["auth-service", "user-service"],
        "duration_minutes": 45,
    },
    {
        "id": "CR-1038",
        "description": "Update npm dependencies in frontend bundle",
        "outcome": "successful",
        "risk_level": "low",
        "affected_systems": ["web-frontend"],
        "duration_minutes": 12,
    },
    {
        "id": "CR-1055",
        "description": "Increase API rate limits for partner endpoints",
        "outcome": "successful",
        "risk_level": "medium",
        "affected_systems": ["api-gateway", "partner-service"],
        "duration_minutes": 8,
    },
    {
        "id": "CR-1061",
        "description": "Deploy new payment processing integration",
        "outcome": "rollback required",
        "risk_level": "high",
        "affected_systems": ["payments", "orders", "billing"],
        "duration_minutes": 120,
    },
]


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_similar_changes",
            description=(
                "Search historical change requests similar to the given description. "
                "Returns past changes with their outcomes and risk levels."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the change request to find similar historical changes for",
                    }
                },
                "required": ["description"],
            },
        ),
        types.Tool(
            name="calculate_risk_score",
            description=(
                "Given a risk level and list of affected systems, return a numeric "
                "risk score (0–100) and a recommended approval tier."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "risk_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "affected_systems": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["risk_level", "affected_systems"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_similar_changes":
        description = arguments.get("description", "").lower()
        keywords = set(description.split())

        # Simple keyword overlap similarity
        scored = []
        for change in HISTORICAL_CHANGES:
            change_words = set(change["description"].lower().split())
            score = len(keywords & change_words)
            if score > 0:
                scored.append((score, change))
        scored.sort(key=lambda x: -x[0])

        results = [c for _, c in scored[:3]] or HISTORICAL_CHANGES[:2]
        return [types.TextContent(type="text", text=json.dumps(results))]

    elif name == "calculate_risk_score":
        risk_level = arguments.get("risk_level", "low")
        affected_systems = arguments.get("affected_systems", [])

        base = {"low": 20, "medium": 50, "high": 80}.get(risk_level, 30)
        system_penalty = min(len(affected_systems) * 5, 20)
        score = min(base + system_penalty, 100)

        tier = (
            "standard" if score < 40
            else "elevated" if score < 70
            else "emergency-cab"
        )

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "score": score,
                "approval_tier": tier,
                "breakdown": {
                    "base_score": base,
                    "system_count_penalty": system_penalty,
                    "affected_system_count": len(affected_systems),
                },
            }),
        )]

    else:
        raise ValueError(f"Unknown tool: {name!r}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
