"""Tests for POST /graphs/{id}/examples and DELETE .../{example_id}."""

import uuid

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.models.graph import Graph
from app.models.user import Org, User


async def _seed(db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="T", slug="test"))
    db_session.add(User(id=DEV_USER_ID, email="t@e.co",
                        display_name="T", org_id=DEV_ORG_ID))
    g = Graph(id=uuid.uuid4(), name="G", slug="g",
              created_by=DEV_USER_ID, org_id=DEV_ORG_ID,
              definition_json={"nodes": [], "edges": []})
    db_session.add(g)
    await db_session.flush()
    return g


async def test_create_example(client, db_session):
    g = await _seed(db_session)

    r = await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={
            "name": "Basic case",
            "input": {"title": "Migrate DB"},
            "output": {"classification": {"risk_level": "high"}},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Basic case"
    assert body["input"] == {"title": "Migrate DB"}
    assert body["output"] == {"classification": {"risk_level": "high"}}
    assert "id" in body
    assert "created_at" in body


async def test_create_example_appears_on_graph(client, db_session):
    g = await _seed(db_session)
    await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={"name": "Ex1", "input": {"a": 1}},
    )
    r = await client.get(f"/api/v1/graphs/{g.id}")
    assert r.status_code == 200
    body = r.json()
    examples = body["test_examples"]
    assert isinstance(examples, list)
    assert len(examples) == 1
    assert examples[0]["name"] == "Ex1"


async def test_delete_example(client, db_session):
    g = await _seed(db_session)
    created = await client.post(
        f"/api/v1/graphs/{g.id}/examples",
        json={"name": "Ex1", "input": {"a": 1}},
    )
    example_id = created.json()["id"]

    r = await client.delete(f"/api/v1/graphs/{g.id}/examples/{example_id}")
    assert r.status_code == 204

    # Gone from the graph
    graph_resp = await client.get(f"/api/v1/graphs/{g.id}")
    assert graph_resp.json()["test_examples"] in (None, [])


async def test_create_example_on_missing_graph_404(client):
    r = await client.post(
        f"/api/v1/graphs/{uuid.uuid4()}/examples",
        json={"name": "X", "input": {}},
    )
    assert r.status_code == 404


async def test_delete_missing_example_404(client, db_session):
    g = await _seed(db_session)
    r = await client.delete(f"/api/v1/graphs/{g.id}/examples/not-a-real-id")
    assert r.status_code == 404
