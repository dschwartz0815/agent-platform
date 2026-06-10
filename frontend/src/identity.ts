/**
 * Client-side identity + workspace selection.
 *
 * In production the SSO reverse proxy injects the X-Auth-* headers and the
 * frontend never sets them. In local dev (no proxy) the UI can simulate any
 * user by storing a "dev identity" here; the API client attaches it to every
 * request. If no dev identity is stored, the backend's dev fallback identity
 * (dev@example.com, agent-platform-admins/-users) applies.
 *
 * The active workspace is always sent via X-Workspace-Id so the backend can
 * scope every query to the selected tenant.
 */

const WORKSPACE_KEY = "ap.activeWorkspaceId";
const DEV_IDENTITY_KEY = "ap.devIdentity";

export interface DevIdentity {
  email: string;
  name: string;
  groups: string[]; // simulated AD groups
}

export function getActiveWorkspaceId(): string | null {
  return localStorage.getItem(WORKSPACE_KEY);
}

export function setActiveWorkspaceId(id: string | null): void {
  if (id) localStorage.setItem(WORKSPACE_KEY, id);
  else localStorage.removeItem(WORKSPACE_KEY);
}

export function getDevIdentity(): DevIdentity | null {
  const raw = localStorage.getItem(DEV_IDENTITY_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as DevIdentity;
  } catch {
    return null;
  }
}

export function setDevIdentity(identity: DevIdentity | null): void {
  if (identity) localStorage.setItem(DEV_IDENTITY_KEY, JSON.stringify(identity));
  else localStorage.removeItem(DEV_IDENTITY_KEY);
}

/** Headers attached to every API request (axios + SSE fetch). */
export function identityHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const dev = getDevIdentity();
  if (dev) {
    headers["X-Auth-User-Email"] = dev.email;
    headers["X-Auth-User-Name"] = dev.name;
    headers["X-Auth-Groups"] = dev.groups.join(",");
  }
  const ws = getActiveWorkspaceId();
  if (ws) headers["X-Workspace-Id"] = ws;
  return headers;
}
