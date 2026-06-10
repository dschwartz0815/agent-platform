import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createGroupMapping,
  createWorkspace,
  deleteGroupMapping,
  listGroupMappings,
} from "../../api/client";
import { getDevIdentity, setDevIdentity } from "../../identity";
import type { Me, Workspace, WorkspaceRole } from "../../types";

interface Props {
  me: Me;
  workspace: Workspace | null;
  onWorkspaceCreated?: () => void;
}

const ROLES: WorkspaceRole[] = ["viewer", "editor", "admin", "owner"];

/**
 * Workspace settings: AD-group → role mappings (the only membership mechanism),
 * new-workspace creation, and the local dev identity simulator.
 */
export function WorkspaceSettings({ me, workspace, onWorkspaceCreated }: Props) {
  return (
    <div style={styles.container}>
      {workspace && <h2 style={{ marginTop: 0 }}>Settings</h2>}
      {workspace && <WorkspaceInfo workspace={workspace} />}
      {workspace && <GroupMappings workspace={workspace} />}
      <CreateWorkspace me={me} onCreated={onWorkspaceCreated} />
      <DevIdentityPanel me={me} />
    </div>
  );
}

function WorkspaceInfo({ workspace }: { workspace: Workspace }) {
  return (
    <section style={styles.section}>
      <h3 style={styles.sectionTitle}>Workspace</h3>
      <div style={styles.infoGrid}>
        <span style={styles.infoLabel}>Name</span><span>{workspace.name}</span>
        <span style={styles.infoLabel}>Slug</span><code>{workspace.slug}</code>
        <span style={styles.infoLabel}>Your role</span><span><RoleBadge role={workspace.role} /></span>
        {workspace.description && (
          <><span style={styles.infoLabel}>Description</span><span>{workspace.description}</span></>
        )}
      </div>
    </section>
  );
}

function GroupMappings({ workspace }: { workspace: Workspace }) {
  const qc = useQueryClient();
  const isAdmin = workspace.role === "admin" || workspace.role === "owner";
  const [adGroup, setAdGroup] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("viewer");
  const [error, setError] = useState<string | null>(null);

  const { data: mappings = [], isLoading } = useQuery({
    queryKey: ["group-mappings", workspace.id],
    queryFn: () => listGroupMappings(workspace.id),
  });

  const addMut = useMutation({
    mutationFn: () => createGroupMapping(workspace.id, { ad_group: adGroup.trim(), role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["group-mappings", workspace.id] });
      setAdGroup("");
      setError(null);
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      setError(detail || "Failed to add mapping.");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (mappingId: string) => deleteGroupMapping(workspace.id, mappingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["group-mappings", workspace.id] });
      setError(null);
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      setError(detail || "Failed to remove mapping.");
    },
  });

  return (
    <section style={styles.section}>
      <h3 style={styles.sectionTitle}>AD group mappings</h3>
      <p style={styles.help}>
        Membership is derived from Active Directory: everyone in a mapped AD group gets
        the mapped role in this workspace. There are no per-user invitations — manage
        access by managing AD groups.
      </p>

      {error && <div style={styles.error}>{error}</div>}

      {isLoading ? (
        <p style={styles.help}>Loading…</p>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>AD group</th>
              <th style={styles.th}>Role</th>
              <th style={styles.th}></th>
            </tr>
          </thead>
          <tbody>
            {mappings.map((m) => (
              <tr key={m.id}>
                <td style={styles.td}><code>{m.ad_group}</code></td>
                <td style={styles.td}><RoleBadge role={m.role} /></td>
                <td style={{ ...styles.td, textAlign: "right" }}>
                  {isAdmin && (
                    <button
                      style={styles.dangerLink}
                      onClick={() => deleteMut.mutate(m.id)}
                      disabled={deleteMut.isPending}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isAdmin && (
        <div style={styles.addRow}>
          <input
            style={styles.input}
            placeholder="AD group name (e.g. eng-platform-team)"
            value={adGroup}
            onChange={(e) => setAdGroup(e.target.value)}
          />
          <select
            style={styles.input}
            value={role}
            onChange={(e) => setRole(e.target.value as WorkspaceRole)}
          >
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button
            style={styles.primaryBtn}
            disabled={!adGroup.trim() || addMut.isPending}
            onClick={() => addMut.mutate()}
          >
            Add mapping
          </button>
        </div>
      )}
    </section>
  );
}

function CreateWorkspace({ me, onCreated }: { me: Me; onCreated?: () => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [ownerGroup, setOwnerGroup] = useState(me.ad_groups[0] ?? "");
  const [error, setError] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () => createWorkspace({ name, slug, owner_group: ownerGroup }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setOpen(false);
      setName("");
      setSlug("");
      setError(null);
      onCreated?.();
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      setError(detail || "Failed to create workspace.");
    },
  });

  return (
    <section style={styles.section}>
      <h3 style={styles.sectionTitle}>New workspace</h3>
      <p style={styles.help}>
        A workspace must be anchored to one of <i>your</i> AD groups — that group
        becomes its owner.
      </p>
      {!open ? (
        <button
          style={styles.primaryBtn}
          onClick={() => setOpen(true)}
          disabled={me.ad_groups.length === 0}
          title={me.ad_groups.length === 0 ? "You have no AD groups" : undefined}
        >
          + Create workspace
        </button>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 480 }}>
          {error && <div style={styles.error}>{error}</div>}
          <input
            style={styles.input}
            placeholder="Name (e.g. Data Engineering)"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
            }}
          />
          <input
            style={styles.input}
            placeholder="Slug (used in public run URLs)"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <select
            style={styles.input}
            value={ownerGroup}
            onChange={(e) => setOwnerGroup(e.target.value)}
          >
            {me.ad_groups.map((g) => <option key={g} value={g}>{g} (owner)</option>)}
          </select>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              style={styles.primaryBtn}
              disabled={!name.trim() || !slug.trim() || !ownerGroup || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              Create
            </button>
            <button style={styles.secondaryBtn} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}

function DevIdentityPanel({ me }: { me: Me }) {
  const stored = getDevIdentity();
  const [email, setEmail] = useState(stored?.email ?? me.email);
  const [name, setName] = useState(stored?.name ?? me.display_name);
  const [groups, setGroups] = useState((stored?.groups ?? me.ad_groups).join(", "));

  const apply = () => {
    setDevIdentity({
      email: email.trim(),
      name: name.trim() || email.trim(),
      groups: groups.split(",").map((g) => g.trim()).filter(Boolean),
    });
    window.location.reload();
  };

  const reset = () => {
    setDevIdentity(null);
    window.location.reload();
  };

  return (
    <section style={styles.section}>
      <h3 style={styles.sectionTitle}>Identity (dev simulator)</h3>
      <p style={styles.help}>
        Signed in as <b>{me.email}</b> with AD groups:{" "}
        {me.ad_groups.length ? <code>{me.ad_groups.join(", ")}</code> : <i>none</i>}.
        In production these come from the SSO proxy headers. For local development you
        can simulate any user and group set here.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 480 }}>
        <input style={styles.input} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input style={styles.input} placeholder="display name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          style={styles.input}
          placeholder="AD groups, comma-separated"
          value={groups}
          onChange={(e) => setGroups(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <button style={styles.primaryBtn} onClick={apply} disabled={!email.trim()}>
            Switch identity
          </button>
          {stored && (
            <button style={styles.secondaryBtn} onClick={reset}>
              Reset to default dev identity
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

function RoleBadge({ role }: { role: WorkspaceRole }) {
  const colors: Record<WorkspaceRole, { bg: string; fg: string }> = {
    owner:  { bg: "#fdf2f8", fg: "#9d174d" },
    admin:  { bg: "#eef2ff", fg: "#4338ca" },
    editor: { bg: "#ecfdf5", fg: "#065f46" },
    viewer: { bg: "#f3f4f6", fg: "#374151" },
  };
  const c = colors[role];
  return (
    <span style={{
      background: c.bg, color: c.fg, borderRadius: 999,
      padding: "2px 10px", fontSize: 11, fontWeight: 700,
    }}>
      {role}
    </span>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 800, margin: "0 auto", padding: 24 },
  section: {
    background: "#fff", border: "1px solid #e5e7eb", borderRadius: 10,
    padding: 20, marginBottom: 20,
  },
  sectionTitle: { margin: "0 0 8px 0", fontSize: 16 },
  help: { color: "#6b7280", fontSize: 13, lineHeight: 1.6, marginTop: 0 },
  infoGrid: {
    display: "grid", gridTemplateColumns: "120px 1fr", rowGap: 8, fontSize: 14,
  },
  infoLabel: { color: "#6b7280", fontSize: 13 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left", padding: "8px 10px", borderBottom: "2px solid #e5e7eb",
    fontSize: 12, color: "#6b7280", textTransform: "uppercase",
  },
  td: { padding: "8px 10px", borderBottom: "1px solid #f3f4f6" },
  addRow: { display: "flex", gap: 8, marginTop: 12 },
  input: {
    border: "1px solid #d1d5db", borderRadius: 6, padding: "8px 10px",
    fontSize: 14, fontFamily: "inherit", flex: 1,
  },
  primaryBtn: {
    background: "#1e293b", color: "#fff", border: "none", borderRadius: 6,
    padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    fontFamily: "inherit",
  },
  secondaryBtn: {
    background: "#fff", color: "#374151", border: "1px solid #d1d5db", borderRadius: 6,
    padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    fontFamily: "inherit",
  },
  dangerLink: {
    background: "none", border: "none", color: "#b91c1c", cursor: "pointer",
    fontSize: 13, fontFamily: "inherit",
  },
  error: {
    background: "#fef2f2", border: "1px solid #fca5a5", color: "#991b1b",
    borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 8,
  },
};
