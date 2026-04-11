"""
LangGraph execution engine.

Given a graph definition_json, builds a real StateGraph, compiles it, and
streams execution events back as dicts suitable for SSE.

Graph definition format
-----------------------
{
  "nodes": [
    {
      "key":         str,          # unique node name in this graph
      "type":        str,          # 'llm' | 'mcp_tool' | 'router' | 'agent' | 'a2a'
      "label":       str,
      "config":      dict          # type-specific, see each _build_* function
    }
  ],
  "edges": [
    {
      "from":       str,           # node_key or '__start__'
      "to":         str,           # node_key or '__end__'
      "condition":  str | null     # non-null only on conditional router edges
    }
  ]
}

State
-----
All nodes share AgentState. LLM / agent nodes append to `messages`.
MCP tool nodes write results into `context[output_key]`.
A2A nodes write the agent's text response into `context[context_key]`.
Router nodes write the chosen route key into `current_route`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, AsyncIterator

from anthropic import AsyncAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.a2a.card import send_message as a2a_send_message
from app.config import settings
from app.engine import mcp_client

log = logging.getLogger(__name__)

_anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    input: dict[str, Any]       # original payload passed to /run
    context: dict[str, Any]     # accumulated tool outputs
    current_route: str | None   # set by router nodes


# ---------------------------------------------------------------------------
# Node builders — each returns an async callable (state) -> partial state
# ---------------------------------------------------------------------------


def _build_llm_node(node_key: str, config: dict):
    """
    config keys:
      model           str   default "claude-3-5-sonnet-20241022"
      system_prompt   str   optional
      tools           list  Anthropic tool definitions for structured output (tool_use)
      parse_json      bool  if true, attempt to extract JSON from response text and
                            write it to context[context_key]
      context_key     str   used when parse_json=True or tools is set
      include_context bool  if true, append a user message with the full state
                            snapshot {input, context} before calling the model.
                            Use for consolidator/summary nodes that need all prior outputs.
    """
    model = config.get("model", "claude-3-5-sonnet-20241022")
    system_prompt = config.get("system_prompt", "")
    tool_defs = config.get("tools", [])
    parse_json = config.get("parse_json", False)
    context_key = config.get("context_key", node_key)
    include_context = config.get("include_context", False)

    async def node(state: AgentState) -> dict:
        anthro_messages = []
        for m in state["messages"]:
            if isinstance(m, HumanMessage):
                anthro_messages.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                anthro_messages.append({"role": "assistant", "content": m.content})

        if not anthro_messages:
            anthro_messages.append(
                {"role": "user", "content": json.dumps(state["input"])}
            )

        if include_context and state.get("context"):
            # Append a structured snapshot so the LLM can see all accumulated outputs
            snapshot = {
                "input": state["input"],
                "context": state.get("context", {}),
            }
            anthro_messages.append(
                {"role": "user", "content": json.dumps(snapshot, default=str)}
            )

        params: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": anthro_messages,
        }
        if system_prompt:
            params["system"] = system_prompt
        if tool_defs:
            params["tools"] = tool_defs
            params["tool_choice"] = {"type": "any"}

        response = await _anthropic.messages.create(**params)

        updates: dict[str, Any] = {}

        if tool_defs and response.stop_reason == "tool_use":
            # Extract structured output from the first tool_use block
            for block in response.content:
                if block.type == "tool_use":
                    updates["context"] = {**state.get("context", {}), context_key: block.input}
                    updates["messages"] = [
                        AIMessage(content=f"[{block.name}] {json.dumps(block.input)}")
                    ]
                    break
        else:
            text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            updates["messages"] = [AIMessage(content=text)]

            if parse_json:
                parsed = _extract_json(text)
                if parsed is not None:
                    updates["context"] = {**state.get("context", {}), context_key: parsed}

        return updates

    node.__name__ = node_key
    return node


def _build_router_node(node_key: str, config: dict):
    """
    config keys:
      source   str   dot-path into state, e.g. "context.assessment.risk_level"
      routes   dict  value → node_key or '__end__'
      default  str   fallback route if value not found in routes
    """
    source = config.get("source", "current_route")
    routes = config.get("routes", {})
    default = config.get("default", "__end__")

    async def node(state: AgentState) -> dict:
        value = _resolve_path(source, state)
        route = routes.get(str(value).lower() if value else "", default)
        log.debug("router %s: source=%r value=%r → route=%r", node_key, source, value, route)
        return {"current_route": route}

    node.__name__ = node_key
    return node


def _build_mcp_tool_node(node_key: str, config: dict, mcp_servers: dict[str, Any]):
    """
    config keys:
      mcp_server_id  str   UUID of the MCPServer row
      tool_name      str
      arguments      dict  values can be "{{path.in.state}}" templates
      output_key     str   where in context to store the result (default: tool_name)
    """
    server_id = config.get("mcp_server_id")
    tool_name = config.get("tool_name", "")
    arg_template = config.get("arguments", {})
    output_key = config.get("output_key", tool_name)

    async def node(state: AgentState) -> dict:
        server = mcp_servers.get(str(server_id))
        if not server:
            raise RuntimeError(
                f"MCP server {server_id!r} not found in graph mcp_servers registry"
            )

        resolved_args = _resolve_templates(arg_template, state)

        result = await mcp_client.call_tool(
            transport=server["transport"],
            url=server.get("url"),
            command=server.get("command"),
            args=server.get("args"),
            env_vars=server.get("env_vars"),
            tool_name=tool_name,
            arguments=resolved_args,
        )

        new_context = {**state.get("context", {}), output_key: result}
        return {
            "context": new_context,
            "messages": [
                AIMessage(content=f"[{tool_name}] {json.dumps(result, default=str)}")
            ],
        }

    node.__name__ = node_key
    return node


def _build_agent_node(node_key: str, config: dict, mcp_servers: dict[str, Any]):
    """
    ReAct-style agent: given a list of MCP servers, builds tool definitions from
    their tool lists, then runs a tool-use loop via the Anthropic API.

    config keys:
      model           str
      system_prompt   str
      mcp_server_ids  list[str]
      max_iterations  int  default 10
    """
    model = config.get("model", "claude-3-5-sonnet-20241022")
    system_prompt = config.get("system_prompt", "")
    server_ids = config.get("mcp_server_ids", [])
    max_iter = config.get("max_iterations", 10)

    async def node(state: AgentState) -> dict:
        tools: list[dict] = []
        server_tool_map: dict[str, tuple[dict, str]] = {}

        for sid in server_ids:
            server = mcp_servers.get(str(sid))
            if not server:
                log.warning("agent node %s: MCP server %s not found, skipping", node_key, sid)
                continue
            try:
                server_tools = await mcp_client.list_tools(
                    transport=server["transport"],
                    url=server.get("url"),
                    command=server.get("command"),
                    args=server.get("args"),
                    env_vars=server.get("env_vars"),
                )
                for t in server_tools:
                    tools.append({
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
                    })
                    server_tool_map[t["name"]] = (server, t["name"])
            except Exception as exc:
                log.error("Failed to list tools from server %s: %s", sid, exc)

        anthro_messages: list[dict] = []
        for m in state["messages"]:
            if isinstance(m, HumanMessage):
                anthro_messages.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                anthro_messages.append({"role": "assistant", "content": m.content})

        if not anthro_messages:
            anthro_messages.append(
                {"role": "user", "content": json.dumps(state["input"])}
            )

        new_messages: list[BaseMessage] = []

        for _ in range(max_iter):
            params: dict[str, Any] = {
                "model": model,
                "max_tokens": 4096,
                "messages": anthro_messages,
            }
            if system_prompt:
                params["system"] = system_prompt
            if tools:
                params["tools"] = tools

            response = await _anthropic.messages.create(**params)

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                new_messages.append(AIMessage(content=text))
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                assistant_content = []
                for block in response.content:
                    assistant_content.append(block)
                    if block.type == "tool_use":
                        server_info = server_tool_map.get(block.name)
                        if not server_info:
                            tool_result_content = f"Error: unknown tool {block.name!r}"
                        else:
                            srv, tname = server_info
                            try:
                                result = await mcp_client.call_tool(
                                    transport=srv["transport"],
                                    url=srv.get("url"),
                                    command=srv.get("command"),
                                    args=srv.get("args"),
                                    env_vars=srv.get("env_vars"),
                                    tool_name=tname,
                                    arguments=block.input,
                                )
                                tool_result_content = json.dumps(result, default=str)
                            except Exception as exc:
                                tool_result_content = f"Error: {exc}"

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_result_content,
                        })

                anthro_messages.append({"role": "assistant", "content": assistant_content})
                anthro_messages.append({"role": "user", "content": tool_results})
                new_messages.append(
                    AIMessage(content=f"[tool calls: {[b.name for b in response.content if b.type == 'tool_use']}]")
                )
            else:
                break

        return {"messages": new_messages}

    node.__name__ = node_key
    return node


def _build_a2a_node(node_key: str, config: dict, agents: dict[str, Any]):
    """
    Calls an external A2A agent via the message/send JSON-RPC protocol.

    config keys:
      agent_id       str   UUID of the Agent row (agent_type='http')
      input_template str   dot-path template for what to send; default: full context as JSON
      context_key    str   where to store the agent's text response in context
    """
    agent_id = config.get("agent_id")
    context_key = config.get("context_key", node_key)
    input_template = config.get("input_template")

    async def node(state: AgentState) -> dict:
        agent = agents.get(str(agent_id))
        if not agent:
            raise RuntimeError(
                f"A2A agent {agent_id!r} not found in graph agents registry"
            )

        url = agent.get("url")
        if not url:
            raise RuntimeError(f"A2A agent {agent_id!r} has no URL")

        # Build the message text: either a resolved template path or full context + input
        if input_template:
            msg_value = _resolve_path(input_template, state)
            message_text = json.dumps(msg_value, default=str)
        else:
            message_text = json.dumps(
                {"input": state["input"], "context": state.get("context", {})},
                default=str,
            )

        result = await a2a_send_message(url, message_text)

        # Extract text from A2A response parts
        parts = result.get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if p.get("kind") == "text")
        if not text:
            # Fallback: stringify the whole result
            text = json.dumps(result, default=str)

        new_context = {**state.get("context", {}), context_key: text}
        return {
            "context": new_context,
            "messages": [AIMessage(content=text)],
        }

    node.__name__ = node_key
    return node


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    definition: dict,
    mcp_servers: dict[str, Any],
    agents: dict[str, Any] | None = None,
) -> Any:
    """
    Compile a LangGraph StateGraph from a definition_json dict.

    mcp_servers: dict keyed by server UUID string → {transport, url, command, args, env_vars}
    agents:      dict keyed by agent UUID string  → {url, ...}

    Router nodes write the destination node name directly into state["current_route"]
    (converting "__end__" to the LangGraph END sentinel at routing time).
    add_conditional_edges reads current_route without a route_map, so it must
    already contain a valid node key or END.
    """
    if agents is None:
        agents = {}

    sg = StateGraph(AgentState)

    node_defs = {n["key"]: n for n in definition.get("nodes", [])}
    edges = definition.get("edges", [])

    # 1. Register all nodes
    for key, nd in node_defs.items():
        ntype = nd["type"]
        cfg = nd.get("config", {})

        if ntype == "llm":
            sg.add_node(key, _build_llm_node(key, cfg))
        elif ntype == "router":
            sg.add_node(key, _build_router_node(key, cfg))
        elif ntype == "mcp_tool":
            sg.add_node(key, _build_mcp_tool_node(key, cfg, mcp_servers))
        elif ntype == "agent":
            sg.add_node(key, _build_agent_node(key, cfg, mcp_servers))
        elif ntype == "a2a":
            sg.add_node(key, _build_a2a_node(key, cfg, agents))
        else:
            raise ValueError(f"Unknown node type: {ntype!r}")

    # 2. Determine which source nodes have conditional (router) outgoing edges
    router_source_keys: set[str] = set()
    for edge in edges:
        if edge.get("condition") is not None:
            src = edge["from"]
            router_source_keys.add(START if src == "__start__" else src)

    # 3. Add normal edges (skip edges whose source is a router — those use conditional edges)
    for edge in edges:
        src = edge["from"]
        tgt = edge["to"]
        cond = edge.get("condition")
        src_lg = START if src == "__start__" else src
        tgt_lg = END if tgt == "__end__" else tgt

        if cond is None and src_lg not in router_source_keys:
            sg.add_edge(src_lg, tgt_lg)

    # 4. Add conditional edges for each router source.
    #    Router nodes store the destination node name in current_route
    #    (already converted to END for "__end__"). No route_map needed.
    def _make_router_fn():
        def _route(state: AgentState) -> Any:
            dest = state.get("current_route")
            return END if dest == "__end__" else dest
        return _route

    for rk in router_source_keys:
        sg.add_conditional_edges(rk, _make_router_fn())

    return sg.compile()


# ---------------------------------------------------------------------------
# Streaming runner
# ---------------------------------------------------------------------------


async def stream_graph(
    definition: dict,
    mcp_servers: dict[str, Any],
    run_input: dict[str, Any],
    agents: dict[str, Any] | None = None,
) -> AsyncIterator[dict]:
    """
    Compile and stream a graph. Yields event dicts:
      {"event": "node_start", "node": "...", "data": null}
      {"event": "token",      "node": "...", "data": "...text..."}
      {"event": "node_end",   "node": "...", "data": {...state slice...}}
      {"event": "done",       "node": null,  "data": {...final state...}}
      {"event": "error",      "node": null,  "data": "...message..."}
    """
    compiled = build_graph(definition, mcp_servers, agents)

    initial: AgentState = {
        "messages": [HumanMessage(content=json.dumps(run_input))],
        "input": run_input,
        "context": {},
        "current_route": None,
    }

    node_keys = {n["key"] for n in definition.get("nodes", [])}

    try:
        async for event in compiled.astream_events(initial, version="v2"):
            kind = event.get("event")
            name = event.get("name", "")

            if kind == "on_chain_start" and name in node_keys:
                yield {"event": "node_start", "node": name, "data": None}

            elif kind == "on_chain_end" and name in node_keys:
                output = event.get("data", {}).get("output", {})
                safe_output: dict[str, Any] = {}
                for k, v in (output or {}).items():
                    if k == "messages":
                        # Serialize message content so the frontend can display LLM output
                        texts = []
                        for m in (v or []):
                            content = m.content if hasattr(m, "content") else m.get("content", "")
                            if content:
                                texts.append(str(content))
                        if texts:
                            safe_output["message_text"] = "\n\n".join(texts)
                    else:
                        safe_output[k] = v
                yield {"event": "node_end", "node": name, "data": safe_output}

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    text = chunk.content
                    if isinstance(text, list):
                        text = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in text
                        )
                    if text:
                        node_name = event.get("metadata", {}).get("langgraph_node", "")
                        yield {"event": "token", "node": node_name, "data": text}

        yield {"event": "done", "node": None, "data": {}}

    except Exception as exc:
        log.exception("Graph execution error")
        yield {"event": "error", "node": None, "data": str(exc)}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _resolve_path(path: str, state: AgentState) -> Any:
    """Resolve a dot-path like 'context.assessment.risk_level' against state."""
    parts = path.split(".")
    obj: Any = state
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _resolve_templates(template: dict, state: AgentState) -> dict:
    """Replace {{path}} placeholders in argument dict values."""
    resolved = {}
    for k, v in template.items():
        if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
            path = v[2:-2].strip()
            resolved[k] = _resolve_path(path, state)
        else:
            resolved[k] = v
    return resolved


def _extract_json(text: str) -> Any | None:
    """Try to extract a JSON object/array from freeform LLM output."""
    m = re.search(r"<json>(.*?)</json>", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None
