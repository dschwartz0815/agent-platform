"""Sanity check — confirms pytest, the fixtures, and the app all wire together."""

async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_graphs_list_empty(client):
    response = await client.get("/api/v1/graphs/")
    assert response.status_code == 200
    assert response.json() == []
