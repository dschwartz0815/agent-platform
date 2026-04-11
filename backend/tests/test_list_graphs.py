"""List graphs endpoint — ensures latest_version_number is populated on summaries."""

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
        name="Listed Graph",
        slug="listed-graph",
        created_by=DEV_USER_ID,
        org_id=DEV_ORG_ID,
        definition_json={
            "nodes": [{"key": "n1", "type": "llm", "config": {}}],
            "edges": [
                {"from": "__start__", "to": "n1", "condition": None},
                {"from": "n1", "to": "__end__", "condition": None},
            ],
        },
    )
    db_session.add(graph)
    await db_session.flush()
    return graph


async def test_list_includes_slug_for_draft_graph(client, db_session):
    graph = await _seed(db_session)
    r = await client.get("/api/v1/graphs/")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["slug"] == "listed-graph"
    # Not yet published → latest_version_number is null
    assert body[0]["latest_version_number"] is None
    assert body[0]["latest_published_version_id"] is None


async def test_list_includes_latest_version_number_after_publish(client, db_session):
    graph = await _seed(db_session)
    pub = await client.post(f"/api/v1/graphs/{graph.id}/publish", json={"notes": "v1"})
    assert pub.status_code == 201

    r = await client.get("/api/v1/graphs/")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["slug"] == "listed-graph"
    assert body[0]["latest_version_number"] == 1
    assert body[0]["latest_published_version_id"] == pub.json()["id"]


async def test_list_handles_multiple_graphs_mixed_state(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test Org", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="test@example.com",
                        display_name="Test User", org_id=DEV_ORG_ID))
    definition = {
        "nodes": [{"key": "n1", "type": "llm", "config": {}}],
        "edges": [
            {"from": "__start__", "to": "n1", "condition": None},
            {"from": "n1", "to": "__end__", "condition": None},
        ],
    }
    g_pub = Graph(id=uuid.uuid4(), name="Published", slug="published",
                  created_by=DEV_USER_ID, org_id=DEV_ORG_ID, definition_json=definition)
    g_draft = Graph(id=uuid.uuid4(), name="Draft Only", slug="draft-only",
                    created_by=DEV_USER_ID, org_id=DEV_ORG_ID, definition_json=definition)
    db_session.add_all([g_pub, g_draft])
    await db_session.flush()

    await client.post(f"/api/v1/graphs/{g_pub.id}/publish", json={"notes": "v1"})
    await client.post(f"/api/v1/graphs/{g_pub.id}/publish", json={"notes": "v2"})

    r = await client.get("/api/v1/graphs/")
    assert r.status_code == 200
    by_slug = {g["slug"]: g for g in r.json()}
    assert by_slug["published"]["latest_version_number"] == 2
    assert by_slug["draft-only"]["latest_version_number"] is None
