"""
Multi-tenancy tests: AD-group-derived identity, workspace isolation, roles,
group-mapping admin, and the cross-workspace catalog.

Identity is asserted per-request via the trusted SSO headers; each test plays
one or more users by sending different header sets through the same client.
"""

import uuid

from app.models.user import Org, TenantGroupMapping


def h(email: str, groups: list[str], workspace: uuid.UUID | None = None) -> dict:
    headers = {
        "X-Auth-User-Email": email,
        "X-Auth-User-Name": email.split("@")[0],
        "X-Auth-Groups": ",".join(groups),
    }
    if workspace:
        headers["X-Workspace-Id"] = str(workspace)
    return headers


async def _two_workspaces(db_session) -> tuple[Org, Org]:
    """Two workspaces with role mappings:
    team-a: ad-a-admins=admin, ad-a-editors=editor, ad-a-viewers=viewer
    team-b: ad-b-owners=owner, ad-b-viewers=viewer
    """
    org_a = Org(id=uuid.uuid4(), name="Team A", slug=f"team-a-{uuid.uuid4().hex[:6]}")
    org_b = Org(id=uuid.uuid4(), name="Team B", slug=f"team-b-{uuid.uuid4().hex[:6]}")
    db_session.add(org_a)
    db_session.add(org_b)
    await db_session.flush()
    for org, group, role in [
        (org_a, "ad-a-admins", "admin"),
        (org_a, "ad-a-editors", "editor"),
        (org_a, "ad-a-viewers", "viewer"),
        (org_b, "ad-b-owners", "owner"),
        (org_b, "ad-b-viewers", "viewer"),
    ]:
        db_session.add(TenantGroupMapping(org_id=org.id, ad_group=group, role=role))
    await db_session.flush()
    return org_a, org_b


# ---------------------------------------------------------------------------
# Identity + membership resolution
# ---------------------------------------------------------------------------

async def test_me_derives_workspaces_from_groups(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    r = await client.get("/api/v1/me", headers=h("alice@corp.com", ["ad-a-editors"]))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@corp.com"
    assert body["ad_groups"] == ["ad-a-editors"]
    assert [w["id"] for w in body["workspaces"]] == [str(org_a.id)]
    assert body["workspaces"][0]["role"] == "editor"


async def test_user_is_jit_provisioned(client, db_session):
    await _two_workspaces(db_session)
    r = await client.get("/api/v1/me", headers=h("new.hire@corp.com", ["ad-a-viewers"]))
    assert r.status_code == 200

    from sqlalchemy import select
    from app.models.user import User
    result = await db_session.execute(
        select(User).where(User.email == "new.hire@corp.com")
    )
    user = result.scalar_one()
    assert user.ad_groups == ["ad-a-viewers"]


async def test_no_matching_groups_means_no_workspace(client, db_session):
    await _two_workspaces(db_session)
    r = await client.get("/api/v1/graphs/", headers=h("outsider@corp.com", ["unrelated-group"]))
    assert r.status_code == 403


async def test_highest_role_wins_across_groups(client, db_session):
    org_a, _ = await _two_workspaces(db_session)
    r = await client.get(
        "/api/v1/workspaces/current",
        headers=h("multi@corp.com", ["ad-a-viewers", "ad-a-admins"], org_a.id),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


async def test_workspace_header_selects_and_hides_non_member(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    # Member of A only: selecting A works, selecting B is a 404
    ok = await client.get(
        "/api/v1/workspaces/current", headers=h("alice@corp.com", ["ad-a-editors"], org_a.id)
    )
    assert ok.status_code == 200
    assert ok.json()["id"] == str(org_a.id)

    denied = await client.get(
        "/api/v1/workspaces/current", headers=h("alice@corp.com", ["ad-a-editors"], org_b.id)
    )
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_registry_isolation_between_workspaces(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    alice = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    bob = h("bob@corp.com", ["ad-b-owners"], org_b.id)

    created = await client.post(
        "/api/v1/agents/",
        json={"name": "A-only agent", "agent_type": "llm", "model": "claude-sonnet-4-6"},
        headers=alice,
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]

    # Bob's workspace doesn't list it and can't fetch, patch, or delete it
    assert (await client.get("/api/v1/agents/", headers=bob)).json() == []
    assert (await client.get(f"/api/v1/agents/{agent_id}", headers=bob)).status_code == 404
    assert (
        await client.patch(f"/api/v1/agents/{agent_id}", json={"name": "x"}, headers=bob)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/agents/{agent_id}", headers=bob)).status_code == 404

    # Alice still sees it
    assert (await client.get(f"/api/v1/agents/{agent_id}", headers=alice)).status_code == 200


async def test_graph_isolation_between_workspaces(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    alice = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    bob = h("bob@corp.com", ["ad-b-owners"], org_b.id)

    created = await client.post("/api/v1/graphs/", json={"name": "Graph A"}, headers=alice)
    assert created.status_code == 201
    graph_id = created.json()["id"]
    assert created.json()["org_id"] == str(org_a.id)

    assert (await client.get("/api/v1/graphs/", headers=bob)).json() == []
    assert (await client.get(f"/api/v1/graphs/{graph_id}", headers=bob)).status_code == 404
    assert (await client.delete(f"/api/v1/graphs/{graph_id}", headers=bob)).status_code == 404


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------

async def test_viewer_reads_but_cannot_write(client, db_session):
    org_a, _ = await _two_workspaces(db_session)
    viewer = h("vic@corp.com", ["ad-a-viewers"], org_a.id)

    assert (await client.get("/api/v1/graphs/", headers=viewer)).status_code == 200
    assert (
        await client.post("/api/v1/graphs/", json={"name": "nope"}, headers=viewer)
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/agents/",
            json={"name": "nope", "agent_type": "llm"},
            headers=viewer,
        )
    ).status_code == 403


async def test_api_keys_require_admin(client, db_session):
    org_a, _ = await _two_workspaces(db_session)
    editor = h("ed@corp.com", ["ad-a-editors"], org_a.id)
    admin = h("alice@corp.com", ["ad-a-admins"], org_a.id)

    assert (
        await client.post(
            "/api/v1/api-keys", json={"name": "k", "scopes": ["*"]}, headers=editor
        )
    ).status_code == 403

    created = await client.post(
        "/api/v1/api-keys", json={"name": "k", "scopes": ["*"]}, headers=admin
    )
    assert created.status_code == 201
    assert created.json()["org_id"] == str(org_a.id)

    # Listing is allowed for any member; plaintext never appears
    listed = await client.get("/api/v1/api-keys", headers=editor)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "key" not in listed.json()[0]


# ---------------------------------------------------------------------------
# Workspace + group-mapping management
# ---------------------------------------------------------------------------

async def test_create_workspace_requires_own_ad_group(client, db_session):
    denied = await client.post(
        "/api/v1/workspaces",
        json={"name": "Sneaky", "slug": "sneaky", "owner_group": "group-i-am-not-in"},
        headers=h("eve@corp.com", ["some-group"]),
    )
    assert denied.status_code == 403

    ok = await client.post(
        "/api/v1/workspaces",
        json={"name": "Data Eng", "slug": "data-eng", "owner_group": "data-eng-team"},
        headers=h("dana@corp.com", ["data-eng-team"]),
    )
    assert ok.status_code == 201
    assert ok.json()["role"] == "owner"

    # Membership is immediately derived from the AD group
    me = await client.get("/api/v1/me", headers=h("dana@corp.com", ["data-eng-team"]))
    assert [w["slug"] for w in me.json()["workspaces"]] == ["data-eng"]


async def test_group_mapping_admin_and_last_owner_guard(client, db_session):
    org_a, _ = await _two_workspaces(db_session)
    admin = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    editor = h("ed@corp.com", ["ad-a-editors"], org_a.id)
    base = f"/api/v1/workspaces/{org_a.id}/group-mappings"

    # Editors can see mappings but not change them
    assert (await client.get(base, headers=editor)).status_code == 200
    assert (
        await client.post(base, json={"ad_group": "x", "role": "viewer"}, headers=editor)
    ).status_code == 403

    # Admin adds a mapping; duplicates are rejected
    created = await client.post(
        base, json={"ad_group": "ad-a-contractors", "role": "viewer"}, headers=admin
    )
    assert created.status_code == 201
    dup = await client.post(
        base, json={"ad_group": "ad-a-contractors", "role": "editor"}, headers=admin
    )
    assert dup.status_code == 409

    # New group works immediately
    r = await client.get("/api/v1/graphs/", headers=h("c@corp.com", ["ad-a-contractors"], org_a.id))
    assert r.status_code == 200

    # The last owner mapping of a workspace cannot be removed
    owners = await client.post(
        base, json={"ad_group": "ad-a-owners", "role": "owner"}, headers=admin
    )
    assert owners.status_code == 201
    owner_mapping_id = owners.json()["id"]
    blocked = await client.delete(f"{base}/{owner_mapping_id}", headers=admin)
    assert blocked.status_code == 422

    # Non-owner mappings delete fine
    ok = await client.delete(f"{base}/{created.json()['id']}", headers=admin)
    assert ok.status_code == 204


async def test_invalid_mapping_role_rejected(client, db_session):
    org_a, _ = await _two_workspaces(db_session)
    admin = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    r = await client.post(
        f"/api/v1/workspaces/{org_a.id}/group-mappings",
        json={"ad_group": "g", "role": "superuser"},
        headers=admin,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

async def test_catalog_publish_browse_install(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    alice = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    bob = h("bob@corp.com", ["ad-b-owners"], org_b.id)

    created = await client.post(
        "/api/v1/agents/",
        json={
            "name": "Shared summarizer",
            "description": "Summarizes anything",
            "agent_type": "llm",
            "model": "claude-sonnet-4-6",
            "system_prompt": "Summarize.",
            "tags": ["nlp"],
        },
        headers=alice,
    )
    agent_id = created.json()["id"]

    # Private entries are invisible in the catalog
    assert (await client.get("/api/v1/catalog", headers=bob)).json() == []

    published = await client.post(f"/api/v1/agents/{agent_id}/publish", headers=alice)
    assert published.status_code == 200
    assert published.json()["visibility"] == "catalog"
    assert published.json()["published_at"] is not None

    # Bob can browse it from workspace B, with provenance
    catalog = (await client.get("/api/v1/catalog", headers=bob)).json()
    assert len(catalog) == 1
    entry = catalog[0]
    assert entry["entry_type"] == "agent"
    assert entry["workspace_id"] == str(org_a.id)
    assert entry["owned_by_caller_workspace"] is False

    # ... and install it into workspace B
    installed = await client.post(f"/api/v1/catalog/agents/{agent_id}/install", headers=bob)
    assert installed.status_code == 201
    copy = installed.json()
    assert copy["org_id"] == str(org_b.id)
    assert copy["visibility"] == "private"
    assert copy["source_id"] == agent_id
    assert copy["system_prompt"] == "Summarize."

    # The copy shows up in B's own registry; A's registry is unchanged
    b_agents = (await client.get("/api/v1/agents/", headers=bob)).json()
    assert [a["id"] for a in b_agents] == [copy["id"]]
    a_agents = (await client.get("/api/v1/agents/", headers=alice)).json()
    assert [a["id"] for a in a_agents] == [agent_id]


async def test_catalog_publish_requires_admin_and_install_requires_editor(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    editor = h("ed@corp.com", ["ad-a-editors"], org_a.id)
    admin = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    b_viewer = h("vb@corp.com", ["ad-b-viewers"], org_b.id)

    created = await client.post(
        "/api/v1/agents/", json={"name": "X", "agent_type": "llm"}, headers=editor
    )
    agent_id = created.json()["id"]

    assert (
        await client.post(f"/api/v1/agents/{agent_id}/publish", headers=editor)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/agents/{agent_id}/publish", headers=admin)
    ).status_code == 200

    assert (
        await client.post(f"/api/v1/catalog/agents/{agent_id}/install", headers=b_viewer)
    ).status_code == 403


async def test_catalog_mcp_server_flow_and_unpublish(client, db_session):
    org_a, org_b = await _two_workspaces(db_session)
    alice = h("alice@corp.com", ["ad-a-admins"], org_a.id)
    bob = h("bob@corp.com", ["ad-b-owners"], org_b.id)

    created = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": "Docs search",
            "transport": "http",
            "url": "http://mcp.internal/sse",
            "tags": ["search"],
        },
        headers=alice,
    )
    assert created.status_code == 201
    server_id = created.json()["id"]

    await client.post(f"/api/v1/mcp-servers/{server_id}/publish", headers=alice)
    entries = (await client.get("/api/v1/catalog?entry_type=mcp_server", headers=bob)).json()
    assert [e["id"] for e in entries] == [server_id]

    installed = await client.post(
        f"/api/v1/catalog/mcp-servers/{server_id}/install", headers=bob
    )
    assert installed.status_code == 201
    assert installed.json()["org_id"] == str(org_b.id)
    assert installed.json()["source_id"] == server_id

    # Installing into the owning workspace is rejected
    own = await client.post(f"/api/v1/catalog/mcp-servers/{server_id}/install", headers=alice)
    assert own.status_code == 422

    # Unpublish removes it from the catalog but keeps Bob's installed copy
    await client.post(f"/api/v1/mcp-servers/{server_id}/unpublish", headers=alice)
    assert (await client.get("/api/v1/catalog", headers=bob)).json() == []
    b_servers = (await client.get("/api/v1/mcp-servers/", headers=bob)).json()
    assert len(b_servers) == 1
