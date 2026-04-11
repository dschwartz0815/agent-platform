# Graph-as-API Design

**Date:** 2026-04-11
**Status:** Spec — approved for planning
**Scope:** Turn any built graph into a documented, versioned, authenticated, testable, observable HTTP API so enterprise teams can consume it end-to-end.

---

## 1. Context

Teams can already build LangGraph-based graphs in the canvas editor, register external A2A agents and MCP servers, and execute graphs via an in-editor Run panel that streams SSE events. What's missing is everything between "I built a graph" and "my production service calls it from Python at 3 AM on a Tuesday":

- No way to invoke a graph as an API from outside the editor
- No versioning, so editing a graph silently breaks every consumer
- No authentication or scoping
- No documentation surface — callers can't see the contract
- No test harness outside of hand-editing JSON in the Run panel
- No persistence of runs, so no observability or cost/latency retrospectives
- No long-running job model — everything is synchronous in a request/response window

This spec defines the feature set that closes all of those gaps for an enterprise MVP.

## 2. Goals

1. **Publish & pin**: Every graph has a draft (the live canvas) and immutable published versions (`v1`, `v2`, …). Callers pin to a version or ride `latest`.
2. **Explicit contract**: Every graph declares its `input_schema` and `output_schema` as JSON Schema. These drive validation, documentation, forms, and examples.
3. **Three delivery modes**: Sync, streaming (SSE), and async (queued + webhook) — one underlying run, three shapes.
4. **Stripe-quality API docs**: A Swagger-like "API Docs" tab auto-generated from the schema, with copy-pasteable curl / python / typescript snippets.
5. **Auth**: Per-org API keys with scope lists. Show-once plaintext at creation, hashed at rest. Stripe-style `ap_live_` prefix.
6. **Observability**: Every run persists to `runs` + `run_steps` tables. Runs tab shows list + per-node waterfall detail. 30-day retention, configurable per graph.
7. **Test harness**: Form-first test panel generated from `input_schema`, with a JSON toggle, saved examples, and recent-run history. Streams live during execution.
8. **Graph detail page**: Replace the click-into-editor behavior with a product-page view (Overview / API Docs / Versions / Keys / Runs / Test), with the canvas editor one click away behind an "Edit" button.

## 3. Non-goals

Explicitly deferred to future work:
- OAuth / OIDC federation (Okta, Azure AD, Google Workspace SSO)
- OpenAPI spec / Postman collection exports
- Permanent webhook subscriptions (only per-request `webhook_url` for now)
- `Idempotency-Key` header support (retry dedup; adds trivially later on top of the `runs` table)
- Output schema validation (output schemas are documentation only; the runner does not validate responses against the declared shape)
- Rate limiting and quotas per key
- Multi-team orgs (namespace URL is ready; data model stays single-org-per-namespace)
- Cost tracking or billing computation (token usage is stored; cost derivation is a later feature)
- Cross-org graph sharing
- Canary routing / A/B splitting between versions
- Cancelation of streaming runs (only async runs are cancelable)
- GraphQL surface
- Generated client SDKs (the curl/py/ts snippets on the API Docs tab are static templates)
- Visual per-node diff on the Versions tab (raw JSON diff only in v1)

## 4. Architecture

Four concepts tie the feature together:

- **Versioning** — graphs have one always-editable draft plus an append-only list of published versions. Each version is an immutable snapshot of the graph's `definition_json`, `input_schema`, and `output_schema`. The runner always executes a specific `graph_version` row, never the live draft (except in-editor test runs that explicitly target the draft).
- **Contract** — graphs carry `input_schema` and `output_schema` as JSON Schema on the draft, frozen into each version. These schemas drive validation, the API Docs tab, the Test tab's form generator, example payloads, and client code snippets.
- **Execution** — the existing runner (`backend/app/engine/runner.py`) gains three thin capabilities: read from a pinned version, persist run + step traces, and run under three delivery shapes (sync, stream, async) sharing a single underlying `run_graph(...)` primitive.
- **Observability** — every invocation writes a `runs` row and one `run_steps` row per node executed. 30-day retention (configurable per graph). Runs are filterable, sortable, and drillable via a waterfall detail view in the UI.

Public callers hit `POST /v1/run/{org_slug}/{graph_slug}` (latest version) or `POST /v1/run/{org_slug}/{graph_slug}@v3` (pinned). Authentication is per-org API keys with scope lists; keys are hashed at rest and shown to the user once at creation.

## 5. Data model

### 5.1 New tables

#### `graph_versions`
Immutable snapshots of a graph at publish time.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `graph_id` | UUID fk → `graphs.id` | `ON DELETE CASCADE` |
| `version` | int | 1-indexed, unique per `graph_id` |
| `definition_json` | jsonb | Frozen runner snapshot |
| `input_schema` | jsonb | Nullable (pre-contract graphs) |
| `output_schema` | jsonb | Nullable |
| `published_by` | UUID fk → `users.id` | |
| `published_at` | timestamptz | |
| `notes` | text | Nullable — release notes |

Unique constraint: `(graph_id, version)`.

#### `api_keys`
Org-level API keys with scope lists.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `org_id` | UUID fk → `orgs.id` | |
| `name` | text | Human-readable identifier ("Staging pipeline") |
| `key_prefix` | text | `ap_live_abcd` — first 12 chars, shown in UI |
| `key_hash` | text | bcrypt/argon2 hash of full key |
| `key_last4` | text | Last 4 chars for UI display |
| `scopes` | jsonb | List of graph UUIDs or the literal `"*"` for all |
| `webhook_secret_hash` | text | Nullable, hash of the HMAC secret, also show-once |
| `created_by` | UUID fk → `users.id` | |
| `created_at` | timestamptz | |
| `last_used_at` | timestamptz | Nullable; updated on successful auth |
| `revoked_at` | timestamptz | Nullable; if set, key rejects |

#### `runs`
One row per graph invocation (editor test or public API).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `graph_id` | UUID fk → `graphs.id` | |
| `graph_version_id` | UUID fk → `graph_versions.id` | Exact snapshot that ran |
| `trigger_source` | enum | `editor_test` \| `api_sync` \| `api_stream` \| `api_async` |
| `api_key_id` | UUID fk → `api_keys.id` | Nullable for editor test runs |
| `status` | enum | `queued` \| `running` \| `succeeded` \| `failed` \| `canceled` |
| `input_json` | jsonb | |
| `output_json` | jsonb | Nullable until complete |
| `error_message` | text | Nullable |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz | Nullable until complete |
| `duration_ms` | int | Computed on completion |
| `token_usage` | jsonb | `{input_tokens, output_tokens, cache_read, cache_creation}` |
| `webhook_url` | text | Nullable; set only on async runs with delivery requested |
| `webhook_delivered_at` | timestamptz | Nullable |

#### `run_steps`
Per-node execution trace.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `run_id` | UUID fk → `runs.id` | `ON DELETE CASCADE` |
| `node_key` | text | |
| `node_type` | text | `llm` / `router` / `a2a` / `mcp_tool` / `agent` |
| `status` | enum | `running` \| `succeeded` \| `failed` \| `skipped` |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz | |
| `duration_ms` | int | |
| `input_snapshot` | jsonb | State slice going into the node |
| `output_snapshot` | jsonb | Partial state update the node returned |
| `token_usage` | jsonb | Nullable; only LLM/agent nodes |
| `error_message` | text | Nullable |

#### `webhook_deliveries`
One row per webhook delivery attempt.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `run_id` | UUID fk → `runs.id` | |
| `attempt_number` | int | 1..5 |
| `url` | text | |
| `status_code` | int | Nullable if request didn't complete |
| `response_body_preview` | text | Nullable, first 500 chars |
| `error` | text | Nullable (connection error, timeout, etc.) |
| `attempted_at` | timestamptz | |
| `responded_at` | timestamptz | Nullable |

### 5.2 Existing table additions

**`graphs`:**

| Column | Type | Notes |
|---|---|---|
| `slug` | text | Unique per `org_id`; friendly path segment (e.g. `change-risk-analyzer`) |
| `input_schema` | jsonb | Nullable; current draft schema |
| `output_schema` | jsonb | Nullable; current draft schema |
| `latest_published_version_id` | UUID fk → `graph_versions.id` | Nullable; convenience pointer |
| `retention_days` | int | Default `30` |
| `test_examples` | jsonb | Nullable; list of `{name, input, output, created_at}` |

**`orgs`:**

| Column | Type | Notes |
|---|---|---|
| `slug` | text | Unique across orgs; used in the URL namespace |

### 5.3 Migration

Single Alembic migration adding all five new tables and all new columns. Every new column is nullable or has a default, so the existing seeded graph upgrades cleanly without data rewrite. The migration must also **backfill `orgs.slug`** for the existing seeded "Demo Org" row (set to `demo`) and **backfill `graphs.slug`** for the seeded "Change Request Risk Analyzer" (set to `change-risk-analyzer`) before enforcing the unique constraint — otherwise the constraint will fail on a non-empty DB. Indexes:
- `graph_versions(graph_id, version)` unique
- `api_keys(key_hash)` for the auth middleware lookup
- `runs(graph_id, started_at desc)` for the Runs tab list query
- `runs(api_key_id, started_at desc)` for per-key usage views
- `run_steps(run_id)` for the detail drawer
- `graphs(org_id, slug)` unique
- `orgs(slug)` unique

## 6. API surface

### 6.1 Public run endpoints

Under a new `/v1/run/...` prefix, deliberately separate from `/api/v1/` so the public API can version independently from the management API.

```
POST /v1/run/{org}/{slug}                 sync, latest version
POST /v1/run/{org}/{slug}@v3              sync, pinned version
POST /v1/run/{org}/{slug}?mode=stream     SSE (text/event-stream)
POST /v1/run/{org}/{slug}?mode=async      returns {run_id, status: "queued"}
GET  /v1/runs/{run_id}                    poll async status
GET  /v1/runs/{run_id}/stream             re-attach to an in-flight stream
```

**Request body (sync / stream / async):**
```json
{
  "input": { ... },
  "webhook_url": "https://..."   // async only, optional
}
```

**Sync response:**
```json
{
  "run_id": "r_...",
  "status": "succeeded",
  "output": { ... }
}
```

**Stream response**: `text/event-stream`, same event shape the editor already uses, with the addition of a first `{"event": "run_started", "data": {"run_id": "r_..."}}` frame so clients can correlate.

**Async response:**
```json
{
  "run_id": "r_...",
  "status": "queued",
  "poll_url": "/v1/runs/r_..."
}
```

**Errors** (checked in this order, to avoid leaking existence of out-of-scope graphs):
- `401` — missing or invalid `Authorization` header
- `404` — `{org}/{slug}` or pinned `@vN` does not exist, OR the key's scope excludes this graph (both conditions return 404 to avoid a scope-enumeration oracle)
- `403` — reserved for future use (e.g. org-level suspensions)
- `410` — version is explicitly revoked (not used in v1 but reserved)
- `422` — request body fails `input_schema` validation; response includes `{error, details: [{field, message}]}`
- `500` — runner error not caught by graph; response omits stack trace, includes `request_id`

### 6.2 Auth middleware

Runs on every `/v1/*` request:

1. Parse `Authorization: Bearer <token>`; 401 if missing or malformed
2. Hash `<token>` with the configured algorithm
3. Look up `api_keys` by `key_hash`; 401 if not found
4. 401 if `revoked_at IS NOT NULL`
5. Resolve the target graph from `{org}/{slug}`
6. 404 if the graph doesn't exist OR if `scopes` is a list and doesn't include the graph id (return identical 404 in both cases so callers can't enumerate what they can't access)
7. Touch `last_used_at`
8. Attach the key metadata and resolved graph to the request context so the runner can tag the `runs` row

### 6.3 Management endpoints

All under existing `/api/v1/` prefix, grouped by resource:

**Graphs:**
```
PATCH  /api/v1/graphs/{id}                   update draft (name, description, slug, schemas, retention_days)
POST   /api/v1/graphs/{id}/publish           snapshot draft → new graph_version row
GET    /api/v1/graphs/{id}/versions          list all published versions
GET    /api/v1/graphs/{id}/versions/{v}      fetch one version's full definition
```

**Examples:**
```
POST   /api/v1/graphs/{id}/examples          save a {name, input, output} example from a run
DELETE /api/v1/graphs/{id}/examples/{exid}   remove an example
```

**Runs & steps:**
```
GET    /api/v1/graphs/{id}/runs              list runs (filterable: status, date range, api_key_id, version)
GET    /api/v1/runs/{run_id}                 full run detail (includes run_steps)
POST   /api/v1/runs/{run_id}/cancel          cancel a queued or running async run — 409 if trigger_source is editor_test / api_sync / api_stream
```

Runs list uses cursor pagination (`?cursor=<opaque>&limit=<n>`) from day one.

The public `GET /v1/runs/{run_id}` and `GET /v1/runs/{run_id}/stream` endpoints (for async polling and stream re-attach) run through the same `/v1/*` auth middleware and additionally require that the caller's `api_key_id` matches the run's `api_key_id`. A different key in the same org cannot poll someone else's run.

**API keys:**
```
GET    /api/v1/api-keys                      list org keys (no plaintext ever)
POST   /api/v1/api-keys                      create; returns plaintext ONCE in response
POST   /api/v1/api-keys/{id}/revoke          mark revoked
DELETE /api/v1/api-keys/{id}                 hard delete (only allowed if never used)
```

## 7. Runner changes

Three surgical modifications to `backend/app/engine/runner.py`:

### 7.1 Version-aware execution
`stream_graph(...)` accepts a `graph_version_id` instead of a raw `definition`. The execution router loads `graph_versions.definition_json` and passes it through. Editor test runs synthesize an ephemeral "draft" version record (not persisted) so the runner signature is uniform.

### 7.2 Persistent runs and steps
A new `run_graph(...)` helper wraps `stream_graph`:

1. Creates the `runs` row with `status = running`
2. On each `on_chain_start` event for a known node, inserts a `run_steps` row with `status = running`
3. On each `on_chain_end`, finalizes the step row with output snapshot, duration, token usage (extracted from Anthropic response metadata carried through state updates)
4. On `done`, finalizes the `runs` row with `status = succeeded`, `output_json`, `duration_ms`, aggregated `token_usage`
5. On `error`, finalizes the `runs` row with `status = failed` and `error_message`

Token usage extraction: since the runner uses the raw Anthropic SDK (not LangChain chat models), `stream_graph` must attach `response.usage` to each LLM-node output update so `run_graph` can read it.

The SSE stream now emits a first `run_started` event carrying the `run_id` so UI and API clients can correlate.

### 7.3 Async execution
New `backend/app/engine/jobs.py` module:
- **Queue**: rows in `runs` with `status = queued` act as the work queue. A small thread pool (3–5 workers, env-configurable) polls every second for queued work, grabs the oldest row, `UPDATE ... SET status = running WHERE id = ? AND status = 'queued'` (atomic claim), invokes `run_graph`, then (if `webhook_url` was set) fires webhook delivery.
- **Startup recovery**: on app startup, any `runs` row stuck in `running` for >10 minutes is marked `failed` with `error_message = "worker restarted mid-run"`. Proper heartbeats can come later.
- **Cancelation**: `POST /api/v1/runs/{run_id}/cancel` flips a `queued` row to `canceled`, or sets a cancelation flag read by the worker loop for `running` rows.

### 7.4 Webhook delivery
A new async function `deliver_webhook(run_id)` invoked by the job worker after a successful or failed async run:

- Builds payload: `{run_id, status, output?, error_message?, started_at, completed_at, token_usage}`
- HMAC-SHA256 signs the payload bytes with the caller's `webhook_secret` (looked up via the run's `api_key_id`)
- Adds `X-Agent-Platform-Signature: sha256=<hex>`
- POSTs to `webhook_url`, logs an attempt row to `webhook_deliveries`
- Retries with exponential backoff on non-2xx responses or network errors: 30s → 2m → 10m → 1h → 6h (max 5 attempts). Delivery is considered successful on 2xx; giving up sets the run's `webhook_delivered_at` to null permanently but the run's own status is still correct.

## 8. Frontend

### 8.1 Navigation model

`App.tsx`'s top-level `View` union expands to:

```ts
type View = "graphs" | "agents" | "mcp-servers" | "api-keys";
```

Header gets a fourth pill: **API Keys**.

The click-into-graph flow restructures. GraphList's `onOpen` handler no longer opens `GraphEditor` — it opens a new `GraphDetail` component. `GraphEditor` is reached from the "Edit" button inside `GraphDetail`, and its back button returns to `GraphDetail` rather than `GraphList`.

### 8.2 `GraphDetail` component

Shell:

```
┌ Header ────────────────────────────────────────────────────────────┐
│ ← Graphs   acme/change-risk-analyzer    v3 (latest) ▾              │
│            <description>                                           │
│                          [✎ Edit] [📋 Copy URL] [Publish v4]       │
├ Tab bar ───────────────────────────────────────────────────────────┤
│ Overview | API Docs | Versions | Keys | Runs | Test                │
└────────────────────────────────────────────────────────────────────┘
```

- **Version dropdown** in the header controls "what am I looking at" across the API Docs, Runs list filter, and Test form. Defaults to `latest`.
- **Edit** opens `GraphEditor` at the draft.
- **Publish vN** is enabled when the draft has ≥1 node AND (no published version exists yet OR the draft differs from `latest`). Button label shows the next version number (`Publish v1` on first publish, `Publish v4` when latest is v3). Clicking opens a confirm modal that asks for release notes, runs pre-publish validation (schemas valid, no dangling refs, draft has ≥1 node), then creates the new `graph_version` row.

### 8.3 Tab content

#### Overview
Summary card. Name, description, owner, latest version + publish date, three-number stat strip ("N nodes · N runs this week · NN% success"), a small read-only mini-canvas preview rendered from the version's `definition_json`, and the raw endpoint URL with a copy button.

#### API Docs
Stripe-style auto-generated reference:
- Live endpoint URL with copy button + mode badges (`sync` / `stream` / `async`)
- **Authentication** — header format + link to Keys tab
- **Request body** — table with Field / Type / Description generated from `input_schema`
- **Response** — table generated from `output_schema`
- **Code examples** — curl / python / typescript tabs (static string templates, not generated SDKs)
- **Example response** — pretty-printed JSON from a saved example if one exists, else synthesized from the schema
- Buttons: "Try in Test" (switches tabs), no OpenAPI or Postman exports in v1
- Contrast: all muted text uses `#374151` or darker on white backgrounds (fix noted from the mockup review)

#### Versions
Table of all published versions. Each row: version, publish date, publisher, release notes preview, and an "Open" action that switches the header version dropdown to that version. Expandable "Diff vs previous" showing a raw JSON diff of `definition_json` + `input_schema` + `output_schema`. Top of page notes: "The current canvas state is always v(latest+1) draft — edit it in the Edit tab".

#### Keys
A filtered view of the top-level API Keys page, pre-scoped to this graph. Card list showing only keys whose `scopes` includes this graph or `"*"`. Includes a "+ New key scoped to this graph" button that pre-fills the scope list with this graph's id. A "See all org keys" link routes to the top-level API Keys page.

#### Runs
`<RunsList>` — sortable, filterable table:
- Columns: date, status badge, duration, caller (API key name or "Editor Test"), trigger source, input preview (first 60 chars)
- Filters: status, date range, api key, version, trigger source
- Row click opens a right-side `<RunDetailDrawer>` (reuses the `shared/Drawer.tsx` primitive):
  - **Summary** — ids, version, duration, token usage
  - **Input JSON** / **Output JSON** — pretty-printed, collapsible
  - **Waterfall** — horizontal bar chart of per-node timing, labeled, click to expand a step's `input_snapshot` / `output_snapshot`, error steps highlighted red
  - **Webhook deliveries** (async only) — attempt list with status codes, latencies, response previews

#### Test
Form-first harness:
- Top strip: "Last 5 runs" chips (colored ✓ / ✗, relative time, click to reload input), "+ New from example" dropdown of saved examples, "Edit as JSON" toggle
- Form body: generated from the version's `input_schema`:
  - `string` → text input
  - `number` → number input
  - `boolean` → checkbox
  - `string enum` → select
  - `array<string>` → tag input (comma or enter to add)
  - nested `object` → fieldset with recursive generation
  - `description` → help text under the field
  - `required` → marked
- **Mode toggle**: sync / stream / async. Defaults to stream so the user sees live node progress.
- Run button executes and renders results in the same way the existing `RunPanel` does (colored risk badge, markdown report, log toggle)
- **Save as example** button next to a successful run saves `{name, input, output}` to `graph.test_examples` and adds it to the examples dropdown
- Form validation errors from the backend surface inline on the offending field

### 8.4 JSON Schema editor

New component `frontend/src/components/shared/JsonSchemaEditor.tsx` used in two places:

1. **`GraphEditor` toolbar button** — "Schemas" opens a right-side drawer with two inner tabs (Input / Output). Each tab has:
   - **Visual mode**: row-per-field editor. Columns: name, type dropdown, required checkbox, description. "Add field" button. Handles: object, string, number, integer, boolean, string enum, array of primitives. **Supports one level of nested object** — deeper nesting requires dropping to JSON mode.
   - **JSON mode**: raw JSON Schema textarea. Visual and JSON modes stay in sync when JSON is valid. If the raw JSON uses features the visual mode can't represent (deeper nesting, `oneOf`, `$ref`), visual mode is disabled with an explanatory badge: "This schema uses advanced features — edit as JSON."
   - **"Generate from last run"** button: pulls the most recent successful `runs` row's input (or output), derives a schema from the observed shape (types, required fields), and fills the editor. User can then edit.

2. **Read-only mode** — same component with `readOnly` prop. Used by the API Docs and Test tabs to render field tables.

### 8.5 Top-level API Keys page

`frontend/src/components/ApiKeyList/` mirrors `AgentList` / `MCPServerList`:

- Card per key: name, prefix + last4, scope chips (graph names or "All graphs"), last used, revoked/active badge
- **+ New Key** button opens a form modal:
  - Name (text)
  - Scope: multi-select of graphs, or "All graphs (*)" checkbox
  - "Include webhook secret" toggle — if on, a second show-once secret is generated alongside the key
- On create, backend returns the plaintext key (and optional webhook secret) in the POST response. The UI transitions to a "**Save this now — you won't see it again**" screen with large copy buttons for the key and secret. Closing that screen is permanent.
- Revoke action with confirm modal. Hard delete is only allowed for keys never used (enforced backend-side).

## 9. Edge cases and error handling

- **Validation failure on public endpoint** — 422 with `{error, details: [{field, message}]}`. Test tab form surfaces errors inline on the field; Runs list shows `failed` status and the error in the detail drawer.
- **Schema-less graphs** — legacy graphs without schemas still work. Public endpoints return a warning header `X-Agent-Platform-Warning: missing-output-schema`. Test tab falls back to the free-form JSON editor only. Publish is still allowed but flags a warning ("graph has no input schema — consumers will be unable to validate requests").
- **Draft with no nodes** — publish refuses with a validation error.
- **Draft with dangling agent/mcp_server refs** — publish scans the definition for `agent_id` / `mcp_server_id` / `mcp_server_ids` and refuses if any are not found in the DB. This is the same scan the existing usages endpoint implements, reused.
- **Async run orphaned by process restart** — on backend startup, the job worker scans for `runs` stuck in `running` for >10 minutes and marks them `failed` with `error_message = "worker restarted mid-run"`.
- **Webhook URL unreachable** — all 5 delivery attempts logged to `webhook_deliveries`. Runs tab row shows a small ⚠ webhook badge.
- **Deleting a graph with published versions** — confirm modal warns. Cascade deletes versions, runs, run_steps, webhook_deliveries. API keys scoped to the graph are not auto-revoked; they remain valid for other scopes and simply stop matching that graph path.
- **Deleting an agent/MCP server while referenced in a published version** — the existing `/agents/{id}/usages` and `/mcp-servers/{id}/usages` endpoints are extended to also scan `graph_versions.definition_json`, not just `graphs.definition_json`. Without this, published versions quietly break when a user deletes a referenced entity, because the scan only sees drafts. Each usage entry should indicate whether it points at a draft (current) or a pinned version (`v2` etc.) so the UI can show `acme/change-risk-analyzer@v2` in the warning list.
- **Retention cleanup** — a daily background job deletes `runs` older than `graph.retention_days`, cascading to `run_steps` and `webhook_deliveries`.
- **Pinned version + schema drift** — if someone pins `@v1` but v1 had no `input_schema`, requests bypass validation (no schema to enforce). Document this as expected behavior.
- **Slug collisions** — enforced at the DB level via `UNIQUE (org_id, slug)`. UI validates before submit and shows a clean "slug taken" error.
- **Token usage plumbing** — the existing runner calls the Anthropic SDK directly (not LangChain). `_build_llm_node` and `_build_agent_node` must extract `response.usage` and attach it to the state update so `run_graph` can persist it to `run_steps.token_usage` and aggregate it into `runs.token_usage`.
- **HMAC for webhooks without a `webhook_secret`** — keys created without the optional webhook secret simply skip the signature header. Recipients can verify IP origin or use TLS mutual auth if they need more.
- **Canceling a streaming run** — out of scope for v1. Only `queued` and async `running` runs are cancelable.

## 10. Testing strategy

### 10.1 Backend
- **Versioning**: publishing creates exactly one immutable row; concurrent publishes don't create duplicate version numbers (tested via a unique constraint)
- **Schema validation**: each JSON Schema primitive type passed matching and mismatching payloads; nested objects; array constraints; enum coverage
- **Auth middleware**: valid key, revoked key, out-of-scope key, missing header, malformed header, wildcard scope, `last_used_at` touched on success
- **Run persistence**: every `stream_graph` invocation writes a `runs` row and one `run_steps` row per executed node; error path finalizes the row; token usage aggregated correctly
- **Async worker**: queued → running → succeeded path; worker-restart orphan detection; cancel path (queued and running); webhook delivery retry ladder
- **Webhook HMAC**: server-computed signature matches recipient-side recomputation using the raw secret; missing secret means header omitted
- **Retention cleanup**: runs older than `retention_days` are deleted along with cascading children; runs younger are kept
- **Publish validation**: dangling refs reject; empty draft rejects; missing schemas warn but don't block

### 10.2 Frontend
No new automated harness. Manual end-to-end verification via `docker compose up --build`:

1. Build a graph in the editor
2. Open Schemas drawer, define input/output schemas (use Generate from last run after one successful run)
3. Publish v1, add release notes
4. Generate an API key scoped to this graph
5. `curl` the public endpoint with the plaintext key, confirm sync response matches the output schema
6. Open Runs tab, find the curl run, open detail drawer, verify waterfall renders and shows all node timings
7. Edit the graph (draft only), change a node, save — confirm callers on `@v1` are still getting the old behavior
8. Publish v2, confirm the version dropdown updates and "latest" resolves to v2
9. Run the Test tab's form in stream mode, watch live node progress
10. Trigger an async run with a `webhook_url` pointing at a test receiver; observe the webhook deliveries table
11. Revoke the key, confirm the next curl call returns 401
12. Delete the graph, confirm cascade cleanup

## 11. Risks

- **Async worker correctness**: threaded workers with atomic DB-level claim are simple but not bulletproof. If scale demands it, swap for a proper queue (Redis/SQS) later. The schema doesn't change; only the worker implementation does.
- **JSON Schema editor scope creep**: a full visual schema editor is a project in itself. The MVP supports a deliberate subset (object, string, number, boolean, enum, array of primitives, one level of nesting). Power users drop to JSON mode for anything else.
- **Token accounting accuracy**: Anthropic cache tokens are tricky. v1 records the raw `usage` dict and defers derivation. If we added cost computation later, we'd want to verify.
- **Schema versioning drift**: published versions freeze their schemas, but the graph's `slug` and `retention_days` are not frozen (they live on the `graphs` row). If we need to freeze those later, we add them to `graph_versions`.
- **Long-term retention**: daily cleanup is fine for hundreds of runs per graph. For thousands per day per graph, a partitioned table + `DROP PARTITION` approach is cleaner; schema-compatible with the v1 design.

## 12. Open questions for implementation

- **HMAC secret hashing vs. encryption** — we're storing `webhook_secret_hash` same pattern as `key_hash`, which means we can't re-show it. The recipient verifies by signing their own payload copy with the secret they saved. This is fine but worth confirming in implementation.
- **Cache-tokens field compatibility** — `token_usage` should be a flexible jsonb so Anthropic's per-model billing shape can evolve without a migration.
- **Runs list pagination** — server-side cursor pagination from day one; the table will grow fast.

---

*End of spec. Implementation plan to be generated next via the writing-plans skill.*
