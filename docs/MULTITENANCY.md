# Multi-tenancy: workspaces from AD groups

The platform is multi-tenant in the style of Dify: every resource (graph, agent,
MCP server, API key, run) lives in exactly one **workspace**, and what a user can
see and do is decided entirely by their **Active Directory groups**.

## How identity flows

```
Browser ──► SSO reverse proxy ──► backend
            (Azure AD App Proxy,      reads:
             ADFS WAP, oauth2-proxy)    X-Auth-User-Email
            authenticates against AD    X-Auth-User-Name
            and injects headers         X-Auth-Groups  (comma-separated)
```

1. The backend **trusts the identity headers** injected by the proxy. It never
   talks to AD directly — group membership arrives with every request, so a
   group change in AD takes effect on the user's next request.
2. Users are **JIT-provisioned**: the first request from a new email creates the
   `users` row. `users.ad_groups` is only an informational cache of the last
   seen groups; authorization always uses the live request headers.
3. **Local development** has no proxy. With `AUTH_DEV_FALLBACK=true` (default),
   header-less requests act as `dev@example.com` with groups
   `agent-platform-admins, agent-platform-users`. The frontend's
   *Settings → Identity (dev simulator)* panel can send arbitrary
   identity headers to simulate other users. Set `AUTH_DEV_FALLBACK=false` in
   production so unproxied requests get 401.

## How membership is derived

There is **no membership table and no invite flow**. The `tenant_group_mappings`
table maps an AD group to a role in a workspace:

| org_id (workspace) | ad_group | role |
|---|---|---|
| demo | agent-platform-admins | owner |
| demo | agent-platform-users | editor |
| ml-research | ml-research-team | owner |

On each request the backend intersects the caller's groups with the mappings:
every matching mapping grants membership, and the **highest role wins** per
workspace. Removing someone from an AD group removes their access instantly.

### Roles

| Role | Grants |
|---|---|
| `viewer` | Read everything in the workspace, run editor tests |
| `editor` | + create/update/delete graphs, agents, MCP servers; publish graph versions; install from catalog |
| `admin`  | + manage API keys, group mappings, catalog publish/unpublish |
| `owner`  | + reserved for destructive workspace operations |

### The active workspace

The frontend sends `X-Workspace-Id` on every call (the header workspace switcher
sets it). The backend verifies the caller's groups grant membership there;
requesting a workspace you're not a member of returns **404** (indistinguishable
from "doesn't exist"). Without the header, the user's first workspace is used.

Creating a workspace (`POST /api/v1/workspaces`) requires an `owner_group` that
is one of the **caller's own** AD groups — so every workspace is reachable
through AD from the moment it exists. The last `owner` mapping of a workspace
can never be deleted.

## Tenancy enforcement rules (backend)

- Every router resolves `WorkspaceContext` via `app/security/identity.py` and
  filters every query by `org_id == ctx.workspace.id`.
- Cross-tenant lookups surface as **404, never 403** — tenants cannot enumerate
  each other's resources.
- Graph execution resolves referenced agents/MCP servers **only within the
  graph's own workspace**, so a hand-crafted definition can't borrow another
  tenant's credentials or servers.
- The public run surface (`POST /v1/run/{org}/{slug}`) is unchanged: API keys
  are workspace-scoped, verified by prefix+bcrypt, and scope mismatches 404.

## The registry catalog

Agents and MCP servers are workspace-private by default. A workspace **admin**
can publish an entry (`visibility='catalog'`), which makes it discoverable by
every workspace under the **Catalog** tab with provenance (owning workspace,
tags, published date).

Consuming a catalog entry means **installing** it: the platform copies the row
into your workspace with `source_id` lineage. Each tenant therefore owns,
audits, and can edit its copy independently; unpublishing later does not break
existing installs.

```
POST /api/v1/agents/{id}/publish          # admin in owning workspace
POST /api/v1/agents/{id}/unpublish
POST /api/v1/mcp-servers/{id}/publish
POST /api/v1/mcp-servers/{id}/unpublish
GET  /api/v1/catalog?entry_type=agent|mcp_server
POST /api/v1/catalog/agents/{id}/install        # editor+ in consuming workspace
POST /api/v1/catalog/mcp-servers/{id}/install
```

## API quick reference

```
GET    /api/v1/me                                    identity, groups, workspaces+roles
GET    /api/v1/workspaces                            my workspaces
POST   /api/v1/workspaces                            create (owner_group must be mine)
GET    /api/v1/workspaces/current                    active workspace + my role
PATCH  /api/v1/workspaces/{id}                       rename/describe (admin+)
GET    /api/v1/workspaces/{id}/group-mappings        list mappings (member)
POST   /api/v1/workspaces/{id}/group-mappings        add mapping (admin+)
DELETE /api/v1/workspaces/{id}/group-mappings/{mid}  remove mapping (admin+, last-owner guarded)
```

All pre-existing `/api/v1/*` resource endpoints now require workspace
membership and honor `X-Workspace-Id`.

## Trying it locally

```bash
# Dev fallback identity = owner of the Demo workspace
curl -s localhost:8000/api/v1/me | jq .

# Simulate an ML researcher (different tenant)
curl -s localhost:8000/api/v1/me \
  -H "X-Auth-User-Email: maria@corp.com" \
  -H "X-Auth-Groups: ml-research-team" | jq .workspaces

# She can't see Demo's graphs...
curl -s localhost:8000/api/v1/graphs/ \
  -H "X-Auth-User-Email: maria@corp.com" \
  -H "X-Auth-Groups: ml-research-team"        # -> []

# ...but can browse the catalog and install the demo MCP server
curl -s localhost:8000/api/v1/catalog \
  -H "X-Auth-User-Email: maria@corp.com" \
  -H "X-Auth-Groups: ml-research-team" | jq '.[].name'
curl -s -X POST \
  localhost:8000/api/v1/catalog/mcp-servers/00000000-0000-0000-0000-000000000010/install \
  -H "X-Auth-User-Email: maria@corp.com" \
  -H "X-Auth-Groups: ml-research-team" | jq .
```

## Production checklist

- [ ] Deploy behind an SSO proxy that strips inbound `X-Auth-*` headers from
      clients and injects authenticated values (critical — the backend trusts them).
- [ ] `AUTH_DEV_FALLBACK=false`
- [ ] `DEBUG=false` (disables the seed and OpenAPI docs)
- [ ] Map your real AD groups under Settings → AD group mappings.
