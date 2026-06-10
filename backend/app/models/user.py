"""
Tenancy core: workspaces (orgs table), users, and AD-group → workspace mappings.

The platform is multi-tenant. A *workspace* (stored in the legacy `orgs` table)
is the tenant boundary: every graph, agent, MCP server, API key, and run belongs
to exactly one workspace.

Membership is NOT stored per-user. It is derived at request time from the
user's Active Directory groups: a TenantGroupMapping row says "anyone in AD
group X is a <role> of workspace Y". AD stays the single source of truth —
moving a user between AD groups immediately changes what they can access here.

Roles (ordered): viewer < editor < admin < owner
  viewer — read everything in the workspace, run editor tests
  editor — + create/update/delete graphs, agents, MCP servers; publish versions
  admin  — + manage API keys, group mappings, catalog publishing
  owner  — + delete the workspace
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Uuid

from app.db import Base

ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}
ROLES = tuple(ROLE_ORDER)


class Org(Base):
    """A workspace (tenant). Table is named `orgs` for historical reasons;
    the API and UI call this a "workspace"."""

    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    users: Mapped[list["User"]] = relationship(back_populates="org")
    group_mappings: Mapped[list["TenantGroupMapping"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )


class User(Base):
    """
    A platform user, JIT-provisioned from SSO headers on first request.

    `ad_groups` caches the AD groups seen on the user's most recent request —
    informational only; authorization always uses the groups from the live
    request, never this cache.

    `org_id` is a legacy column from the single-tenant era (kept nullable for
    old rows); workspace membership is derived from AD groups, not from it.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ad_groups: Mapped[list | None] = mapped_column(JSON, nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("orgs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    org: Mapped["Org | None"] = relationship(back_populates="users")


class TenantGroupMapping(Base):
    """
    Grants a role in a workspace to every member of an AD group.

    A user's effective role in a workspace is the highest role among all
    mappings whose ad_group appears in their AD groups.
    """

    __tablename__ = "tenant_group_mappings"
    __table_args__ = (
        UniqueConstraint("org_id", "ad_group", name="uq_group_mapping_org_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    ad_group: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # 'viewer' | 'editor' | 'admin' | 'owner'
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    org: Mapped["Org"] = relationship(back_populates="group_mappings")
