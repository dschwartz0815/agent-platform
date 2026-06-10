"""
Identity + tenancy resolution for the management API (/api/v1/*).

Flow per request:
  1. get_current_user — read SSO headers (or dev fallback), JIT-provision the
     User row, return CurrentUser(user, groups).
  2. resolve_memberships — derive (workspace, role) pairs from the user's AD
     groups via tenant_group_mappings. Highest role wins per workspace.
  3. get_workspace_context — pick the active workspace from the X-Workspace-Id
     header (or the user's first workspace) and verify membership.

Routers depend on get_workspace_context and call require_role for writes:

    @router.post("/")
    async def create_thing(
        body: ThingCreate,
        ctx: WorkspaceContext = Depends(get_workspace_context),
        db: AsyncSession = Depends(get_db),
    ):
        require_role(ctx, "editor")
        thing = Thing(..., org_id=ctx.workspace.id, created_by=ctx.user.id)

Tenancy invariant: every query in a router must filter by
`org_id == ctx.workspace.id`; cross-workspace rows surface as 404, never 403,
so tenants can't enumerate each other's resources.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import Org, ROLE_ORDER, TenantGroupMapping, User

log = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    user: User
    groups: list[str]


@dataclass
class Membership:
    org: Org
    role: str


@dataclass
class WorkspaceContext:
    user: User
    groups: list[str]
    workspace: Org
    role: str
    memberships: list[Membership]


def _parse_groups(raw: str) -> list[str]:
    """Header value → group list. Accepts comma or semicolon separators."""
    return [g.strip() for g in raw.replace(";", ",").split(",") if g.strip()]


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    Resolve the caller's identity from SSO-injected headers and JIT-provision
    a User row. 401 when headers are absent and the dev fallback is disabled.
    """
    email = (request.headers.get(settings.auth_user_header) or "").strip().lower()
    if email:
        name = (request.headers.get(settings.auth_name_header) or "").strip() or email
        groups = _parse_groups(request.headers.get(settings.auth_groups_header) or "")
    elif settings.auth_dev_fallback:
        email = settings.dev_user_email
        name = settings.dev_user_name
        groups = list(settings.dev_user_groups)
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(email=email, display_name=name, ad_groups=groups, last_seen_at=now)
        db.add(user)
        await db.flush()
        log.info("user_provisioned", extra={"email": email, "group_count": len(groups)})
    else:
        if user.display_name != name:
            user.display_name = name
        if (user.ad_groups or []) != groups:
            user.ad_groups = groups
        user.last_seen_at = now
        await db.flush()

    return CurrentUser(user=user, groups=groups)


async def resolve_memberships(db: AsyncSession, groups: list[str]) -> list[Membership]:
    """
    Derive workspace memberships from AD groups. When several of the user's
    groups map into the same workspace, the highest role wins.
    """
    if not groups:
        return []
    result = await db.execute(
        select(TenantGroupMapping, Org)
        .join(Org, TenantGroupMapping.org_id == Org.id)
        .where(TenantGroupMapping.ad_group.in_(groups))
        .order_by(Org.created_at)
    )
    best: dict[uuid.UUID, Membership] = {}
    for mapping, org in result.all():
        current = best.get(org.id)
        if current is None or ROLE_ORDER[mapping.role] > ROLE_ORDER[current.role]:
            best[org.id] = Membership(org=org, role=mapping.role)
    return sorted(best.values(), key=lambda m: (m.org.created_at, m.org.slug))


async def get_workspace_context(
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceContext:
    """
    Resolve the active workspace. 403 when the user's AD groups grant no
    workspace at all; 404 when an explicitly requested workspace isn't one of
    theirs (indistinguishable from "doesn't exist").
    """
    memberships = await resolve_memberships(db, current.groups)
    if not memberships:
        raise HTTPException(
            status_code=403,
            detail="Your AD groups do not grant access to any workspace",
        )

    raw_id = (request.headers.get(settings.workspace_header) or "").strip()
    if raw_id:
        try:
            ws_id = uuid.UUID(raw_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace id")
        for m in memberships:
            if m.org.id == ws_id:
                return WorkspaceContext(
                    user=current.user, groups=current.groups,
                    workspace=m.org, role=m.role, memberships=memberships,
                )
        raise HTTPException(status_code=404, detail="Workspace not found")

    first = memberships[0]
    return WorkspaceContext(
        user=current.user, groups=current.groups,
        workspace=first.org, role=first.role, memberships=memberships,
    )


def require_role(ctx: WorkspaceContext, minimum: str) -> None:
    """Raise 403 unless the caller's role in the active workspace is >= minimum."""
    if ROLE_ORDER[ctx.role] < ROLE_ORDER[minimum]:
        raise HTTPException(
            status_code=403,
            detail=f"Requires the '{minimum}' role in this workspace (you are '{ctx.role}')",
        )
