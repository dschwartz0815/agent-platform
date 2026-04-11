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
