"""Sanity check — confirms pytest, the fixtures, and the app all wire together."""

from app.config import DEV_ORG_ID
from app.models.user import Org


async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_graphs_list_empty(client, db_session):
    db_session.add(Org(id=DEV_ORG_ID, name="Test", slug="test"))
    await db_session.flush()
    response = await client.get("/api/v1/graphs/")
    assert response.status_code == 200
    assert response.json() == []
