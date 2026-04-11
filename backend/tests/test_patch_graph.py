"""PATCH /graphs/{id} — slug + schema updates."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(
        id=DEV_USER_ID,
        email="test@example.com",
        display_name="Test User",
        org_id=DEV_ORG_ID,
    ))
    graph = Graph(
        id=uuid.uuid4(),
        name="Test Graph",
        slug="original-slug",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={"nodes": [], "edges": []},
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_patch_slug(client, db_session):
    graph = await _seed(db_session)
    r = await client.patch(
        f"/api/v1/graphs/{graph.id}",
        json={"slug": "new-slug"},
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "new-slug"


async def test_patch_schemas(client, db_session):
    graph = await _seed(db_session)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    r = await client.patch(
        f"/api/v1/graphs/{graph.id}",
        json={"input_schema": schema, "output_schema": schema},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["input_schema"] == schema
    assert body["output_schema"] == schema


async def test_patch_slug_collision_within_org(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    a = Graph(id=uuid.uuid4(), name="A", slug="alpha",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    b = Graph(id=uuid.uuid4(), name="B", slug="beta",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add_all([a, b])
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/graphs/{b.id}",
        json={"slug": "alpha"},
    )
    assert r.status_code == 409
    assert "slug" in r.json()["error"].lower()
