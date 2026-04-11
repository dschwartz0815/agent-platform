"""
A2A Agent Card fetch and validation.

The A2A spec (https://a2aproject.github.io/A2A/) defines a standard agent discovery
mechanism: an agent card served at GET /.well-known/agent.json.

The card describes the agent's identity, capabilities, and skills. This module fetches
the card from a given base URL and validates it against the expected schema.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Card schema (subset of the A2A spec we care about)
# ---------------------------------------------------------------------------


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str | None = None
    inputModes: list[str] = ["text"]
    outputModes: list[str] = ["text"]
    tags: list[str] = []
    examples: list[str] = []


class AgentCard(BaseModel):
    """Validated representation of an A2A agent card."""
    name: str
    description: str | None = None
    url: str
    version: str = "1.0"
    capabilities: AgentCapabilities = AgentCapabilities()
    skills: list[AgentSkill] = []
    # Optional metadata fields
    documentationUrl: str | None = None
    provider: dict | None = None


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def card_url_from_base(base_url: str) -> str:
    """Return the canonical agent card URL for a given agent base URL."""
    return base_url.rstrip("/") + "/.well-known/agent.json"


async def fetch_agent_card(base_url: str, timeout: float = 10.0) -> AgentCard:
    """
    Fetch and validate the agent card from /.well-known/agent.json.

    Raises:
        httpx.HTTPError: if the request fails
        pydantic.ValidationError: if the response doesn't match the expected schema
    """
    url = card_url_from_base(base_url)
    log.info("fetching_agent_card", extra={"url": url})

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    card = AgentCard.model_validate(data)
    log.info(
        "agent_card_fetched",
        extra={"agent_name": card.name, "skills": len(card.skills)},
    )
    return card


async def try_fetch_agent_card(base_url: str) -> dict | None:
    """
    Best-effort agent card fetch. Returns the raw dict on success, None on any error.
    Logs a warning if the fetch fails so the caller can proceed without the card.
    """
    try:
        card = await fetch_agent_card(base_url)
        return card.model_dump()
    except (httpx.HTTPError, ValidationError, Exception) as exc:
        log.warning(
            "agent_card_fetch_failed",
            extra={"url": base_url, "error": str(exc)},
        )
        return None


# ---------------------------------------------------------------------------
# A2A message/send client
# ---------------------------------------------------------------------------


async def send_message(
    agent_url: str,
    message_text: str,
    *,
    task_id: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    Send a message to an A2A agent via the message/send JSON-RPC method.

    Returns the raw result dict from the agent's response.

    Protocol reference:
      POST {agent_url}
      Content-Type: application/json
      Body: {"jsonrpc":"2.0","method":"message/send","params":{"message":{...}},"id":"..."}
    """
    import uuid as _uuid

    rpc_id = task_id or str(_uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message_text}],
            }
        },
        "id": rpc_id,
    }

    log.info("a2a_send_message", extra={"url": agent_url, "rpc_id": rpc_id})

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(agent_url, json=payload)
        resp.raise_for_status()
        body = resp.json()

    if "error" in body:
        raise RuntimeError(f"A2A agent returned error: {body['error']}")

    return body.get("result", {})
