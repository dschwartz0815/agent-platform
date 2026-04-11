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
