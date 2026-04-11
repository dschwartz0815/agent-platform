"""
Mock A2A Agent — "Change Risk Narrative Assessor"

A minimal FastAPI service that:
  - Serves GET /.well-known/agent.json  (A2A agent card)
  - Accepts POST /  (A2A JSON-RPC message/send)

The agent returns a realistic-looking narrative assessment for change request risk.
No LLM calls — all responses are deterministic so the demo works without extra API costs.

Run standalone:
    uvicorn seed_services.mock_a2a_agent:app --port 8001

In docker-compose this service is named `seed-agent` and reachable at http://seed-agent:8001.
"""

import json
import logging
import random
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

app = FastAPI(title="Mock A2A Agent — Change Risk Assessor", docs_url="/docs")

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD = {
    "name": "Change Risk Narrative Assessor",
    "description": (
        "Provides detailed narrative risk assessments for software change requests. "
        "Analyzes impact, rollback complexity, and recommends approval conditions."
    ),
    "url": "http://seed-agent:8001",
    "version": "1.0.0",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "skills": [
        {
            "id": "change-risk-assessment",
            "name": "Change Risk Assessment",
            "description": (
                "Given a change request context (title, description, affected services, "
                "classification, and dependency data), produces a narrative assessment "
                "with risk summary, impact analysis, rollback plan, and approval conditions."
            ),
            "inputModes": ["text"],
            "outputModes": ["text"],
            "tags": ["risk", "change-management", "devops"],
            "examples": [
                "Assess risk for database schema migration affecting payments service",
                "Evaluate impact of load balancer config change during peak hours",
            ],
        }
    ],
    "provider": {
        "organization": "Demo Org",
        "url": "http://seed-agent:8001",
    },
}


@app.get("/.well-known/agent.json")
async def agent_card():
    """A2A agent card discovery endpoint."""
    return JSONResponse(content=AGENT_CARD)


# ---------------------------------------------------------------------------
# A2A message/send endpoint
# ---------------------------------------------------------------------------

_RISK_NARRATIVES = {
    "high": [
        (
            "**Assessment: HIGH RISK — Recommend Enhanced Review**\n\n"
            "This change touches critical path components with broad blast radius. "
            "Based on dependency analysis, {service_count} downstream services are at risk of cascading failures. "
            "The proposed change window ({window}) overlaps with historically high-traffic periods.\n\n"
            "**Impact Analysis:**\n"
            "- Primary risk: service degradation or outage in {services}\n"
            "- Secondary risk: data consistency issues if rollback is required mid-deployment\n"
            "- Estimated blast radius: HIGH (core infrastructure)\n\n"
            "**Rollback Complexity:** HIGH — requires coordinated multi-service rollback. "
            "Estimated recovery time: 45–90 minutes.\n\n"
            "**Approval Conditions:**\n"
            "1. Mandatory change advisory board (CAB) review required\n"
            "2. Canary deployment to 5% traffic minimum 24h before full rollout\n"
            "3. On-call engineers for all affected services must be paged in\n"
            "4. Rollback runbook must be pre-approved and rehearsed\n"
            "5. Change window should be rescheduled to off-peak hours (02:00–04:00 UTC)"
        ),
    ],
    "medium": [
        (
            "**Assessment: MEDIUM RISK — Conditional Approval**\n\n"
            "This change has moderate scope. Dependency analysis shows {service_count} services "
            "may be indirectly affected. The risk is manageable with proper precautions.\n\n"
            "**Impact Analysis:**\n"
            "- Primary scope: {services}\n"
            "- Indirect dependencies should be monitored closely for 30 minutes post-deployment\n"
            "- Estimated blast radius: MEDIUM (isolated subsystem)\n\n"
            "**Rollback Complexity:** MEDIUM — single-service rollback feasible within 15 minutes.\n\n"
            "**Approval Conditions:**\n"
            "1. Peer review sign-off from a senior engineer required\n"
            "2. Staging environment validation mandatory (minimum 1h soak time)\n"
            "3. On-call engineer for primary service must acknowledge change\n"
            "4. Automated smoke tests must pass post-deployment\n"
            "5. Monitor error rates for 15 minutes before closing change"
        ),
    ],
    "low": [
        (
            "**Assessment: LOW RISK — Standard Approval**\n\n"
            "This change has limited scope and isolated impact. "
            "No critical dependencies are at risk.\n\n"
            "**Impact Analysis:**\n"
            "- Scope: confined to {services}\n"
            "- No downstream service impact expected\n"
            "- Estimated blast radius: LOW\n\n"
            "**Rollback Complexity:** LOW — simple revert, estimated 5 minutes.\n\n"
            "**Approval Conditions:**\n"
            "1. Standard peer review sufficient\n"
            "2. No additional approvals required\n"
            "3. Monitor standard dashboards for 10 minutes post-deployment"
        ),
    ],
}


def _generate_assessment(context: dict) -> str:
    """Generate a deterministic-looking narrative from the context dict."""
    # Try to extract structured context
    inner_ctx = context.get("context", context)
    classification = inner_ctx.get("classification", {})
    risk_level = str(classification.get("risk_level", "medium")).lower()
    if risk_level not in ("high", "medium", "low"):
        risk_level = "medium"

    inp = context.get("input", {})
    affected = inp.get("affected_services", ["unknown-service"])
    if isinstance(affected, str):
        affected = [affected]
    services = ", ".join(affected) if affected else "unknown service"
    service_count = len(affected)
    window = inp.get("proposed_window", "TBD")

    # Grab dependency data if present
    dep_data = inner_ctx.get("dependencies")
    if dep_data:
        all_deps = []
        if isinstance(dep_data, dict):
            for svc_deps in dep_data.values():
                if isinstance(svc_deps, list):
                    all_deps.extend(svc_deps)
        service_count = max(service_count, len(all_deps))

    template = random.choice(_RISK_NARRATIVES[risk_level])
    return template.format(
        service_count=service_count,
        services=services,
        window=window,
    )


@app.post("/")
async def handle_message(request: Request):
    """A2A JSON-RPC endpoint — handles message/send method."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
        )

    rpc_id = body.get("id", str(uuid.uuid4()))
    method = body.get("method")

    if method != "message/send":
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": rpc_id,
        })

    params = body.get("params", {})
    message = params.get("message", {})
    parts = message.get("parts", [])

    # Extract text from the first text part
    text = ""
    for part in parts:
        if part.get("kind") == "text":
            text = part.get("text", "")
            break

    # Parse the context JSON that the runner sends
    try:
        context = json.loads(text) if text else {}
    except (json.JSONDecodeError, TypeError):
        context = {"raw": text}

    narrative = _generate_assessment(context)

    log.info("a2a_assessment_generated", extra={"rpc_id": rpc_id, "risk_level": context.get("context", {}).get("classification", {}).get("risk_level", "unknown")})

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "result": {
            "role": "agent",
            "parts": [{"kind": "text", "text": narrative}],
        },
        "id": rpc_id,
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
