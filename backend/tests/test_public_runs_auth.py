"""Auth dependency tests — 401/404 edge cases on public run endpoints."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed_graph(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Acme", slug="acme"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(
        id=uuid.uuid4(),
        name="Test",
        slug="test-graph",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "echo", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "echo", "condition": None},
                {"from": "echo", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g)
    await db_session.flush()
    return g


async def _create_key(client, name: str, scopes: list[str]) -> dict:
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "scopes": scopes},
    )
    assert r.status_code == 201
    return r.json()


async def test_missing_auth_header_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
    )
    assert r.status_code == 401


async def test_malformed_auth_header_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": "NotBearer xyz"},
    )
    assert r.status_code == 401


async def test_invalid_key_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": "Bearer ap_live_notarealkey00000000000000"},
    )
    assert r.status_code == 401


async def test_revoked_key_returns_401(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "revoke-me", ["*"])
    plaintext = key["key"]

    revoke_r = await client.post(f"/api/v1/api-keys/{key['id']}/revoke")
    assert revoke_r.status_code == 200

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert r.status_code == 401


async def test_wildcard_scope_allows_any_graph(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "node_start", "node": "echo", "data": None}
        yield {"event": "node_end", "node": "echo", "data": {"message_text": "ok"}}
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "wildcard", ["*"])

    r = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 200


async def test_specific_scope_allows_only_that_graph(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    g_other = Graph(
        id=uuid.uuid4(),
        name="Other",
        slug="other",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "n", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "n", "condition": None},
                {"from": "n", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(g_other)
    await db_session.flush()

    key = await _create_key(client, "scoped", [str(g.id)])

    ok = await client.post(
        f"/v1/run/acme/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert ok.status_code == 200

    # Out-of-scope: 404 (deliberately not 403 — avoids enumeration)
    not_ok = await client.post(
        f"/v1/run/acme/{g_other.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert not_ok.status_code == 404


async def test_missing_graph_slug_returns_404(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    await _seed_graph(db_session)
    key = await _create_key(client, "k", ["*"])

    r = await client.post(
        "/v1/run/acme/does-not-exist",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 404


async def test_missing_org_slug_returns_404(client, db_session, monkeypatch):
    async def fake_stream(*a, **kw):
        yield {"event": "done", "node": None, "data": {}}
    monkeypatch.setattr("app.engine.persistence.stream_graph", fake_stream)

    g = await _seed_graph(db_session)
    key = await _create_key(client, "k", ["*"])

    r = await client.post(
        f"/v1/run/wrong-org/{g.slug}",
        json={"input": {}},
        headers={"Authorization": f"Bearer {key['key']}"},
    )
    assert r.status_code == 404
