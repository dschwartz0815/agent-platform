"""Tests for /api/v1/api-keys management endpoints."""

import uuid

from sqlalchemy import select

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.api_key import ApiKey
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    await db_session.flush()


async def test_create_key_returns_plaintext_once(client, db_session):
    await _seed(db_session)

    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "CI pipeline", "scopes": ["*"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "CI pipeline"
    assert body["scopes"] == ["*"]
    assert body["key"].startswith("ap_live_")  # plaintext shown once
    assert "key_prefix" in body
    assert body["key_prefix"] == body["key"][:16]
    assert body["key_last4"] == body["key"][-4:]
    assert body["revoked_at"] is None
    assert "id" in body


async def test_list_keys_never_returns_plaintext(client, db_session):
    await _seed(db_session)
    await client.post("/api/v1/api-keys", json={"name": "k1", "scopes": ["*"]})
    await client.post("/api/v1/api-keys", json={"name": "k2", "scopes": ["*"]})

    r = await client.get("/api/v1/api-keys")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    for k in body:
        assert "key" not in k  # plaintext NEVER in list response
        assert "key_hash" not in k  # hash also never exposed
        assert k["key_prefix"].startswith("ap_live_")
        assert len(k["key_last4"]) == 4


async def test_list_keys_ordered_newest_first(client, db_session):
    await _seed(db_session)
    r1 = await client.post("/api/v1/api-keys", json={"name": "first", "scopes": ["*"]})
    r2 = await client.post("/api/v1/api-keys", json={"name": "second", "scopes": ["*"]})

    r = await client.get("/api/v1/api-keys")
    body = r.json()
    # Newest first
    assert body[0]["name"] == "second"
    assert body[1]["name"] == "first"


async def test_create_key_with_graph_scope(client, db_session):
    await _seed(db_session)
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()

    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "graph-scoped", "scopes": [str(g.id)]},
    )
    assert r.status_code == 201
    assert r.json()["scopes"] == [str(g.id)]


async def test_revoke_key(client, db_session):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "to revoke", "scopes": ["*"]},
    )
    key_id = created.json()["id"]

    r = await client.post(f"/api/v1/api-keys/{key_id}/revoke")
    assert r.status_code == 200
    body = r.json()
    assert body["revoked_at"] is not None
    assert "key" not in body


async def test_delete_key(client, db_session):
    await _seed(db_session)
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "to delete", "scopes": ["*"]},
    )
    key_id = created.json()["id"]

    r = await client.delete(f"/api/v1/api-keys/{key_id}")
    assert r.status_code == 204

    r2 = await client.get("/api/v1/api-keys")
    assert all(k["id"] != key_id for k in r2.json())


async def test_create_key_name_required(client, db_session):
    await _seed(db_session)
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "", "scopes": ["*"]},
    )
    assert r.status_code == 422


async def test_create_key_scopes_required(client, db_session):
    await _seed(db_session)
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "k", "scopes": []},
    )
    assert r.status_code == 422


async def test_revoke_missing_key_404(client, db_session):
    await _seed(db_session)
    r = await client.post(f"/api/v1/api-keys/{uuid.uuid4()}/revoke")
    assert r.status_code == 404


async def test_delete_missing_key_404(client, db_session):
    await _seed(db_session)
    r = await client.delete(f"/api/v1/api-keys/{uuid.uuid4()}")
    assert r.status_code == 404
