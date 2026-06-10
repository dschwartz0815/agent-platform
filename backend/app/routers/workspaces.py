"""
Identity + workspace management endpoints.

GET    /api/v1/me                                  — who am I, my groups, my workspaces
GET    /api/v1/workspaces                          — workspaces my AD groups grant me
POST   /api/v1/workspaces                          — create a workspace (AD-group-anchored)
GET    /api/v1/workspaces/current                  — the active workspace + my role
PATCH  /api/v1/workspaces/{id}                     — rename / re-describe (admin+)
GET    /api/v1/workspaces/{id}/group-mappings      — list AD-group → role mappings
POST   /api/v1/workspaces/{id}/group-mappings      — add a mapping (admin+)
DELETE /api/v1/workspaces/{id}/group-mappings/{id} — remove a mapping (admin+)

There is no "invite user" endpoint by design: access is granted by putting
people in AD groups and mapping those groups here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import Org, ROLE_ORDER, TenantGroupMapping
from app.schemas.workspace import (
    GroupMappingCreate,
    GroupMappingOut,
    MeOut,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.security.identity import (
    CurrentUser,
    Membership,
    WorkspaceContext,
    get_current_user,
    get_workspace_context,
    require_role,
    resolve_memberships,
)

router = APIRouter(tags=["workspaces"])


def _ws_out(org: Org, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        description=org.description,
        created_at=org.created_at,
        role=role,
    )


async def _require_membership(
    workspace_id: uuid.UUID,
    current: CurrentUser,
    db: AsyncSession,
    minimum: str = "viewer",
) -> Membership:
    """Membership check for endpoints addressing an explicit workspace id
    (independent of the X-Workspace-Id header). 404 on non-membership."""
    memberships = await resolve_memberships(db, current.groups)
    for m in memberships:
        if m.org.id == workspace_id:
            if ROLE_ORDER[m.role] < ROLE_ORDER[minimum]:
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires the '{minimum}' role in this workspace",
                )
            return m
    raise HTTPException(status_code=404, detail="Workspace not found")


@router.get("/me", response_model=MeOut)
async def get_me(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    memberships = await resolve_memberships(db, current.groups)
    return MeOut(
        id=current.user.id,
        email=current.user.email,
        display_name=current.user.display_name,
        ad_groups=current.groups,
        workspaces=[_ws_out(m.org, m.role) for m in memberships],
    )


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    memberships = await resolve_memberships(db, current.groups)
    return [_ws_out(m.org, m.role) for m in memberships]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # The owner group must be one of the caller's own AD groups, so every
    # workspace is reachable through AD from the moment it exists.
    if body.owner_group not in current.groups:
        raise HTTPException(
            status_code=403,
            detail=f"owner_group '{body.owner_group}' is not one of your AD groups",
        )

    dup = await db.execute(select(Org).where(Org.slug == body.slug))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"slug '{body.slug}' already in use")

    org = Org(name=body.name, slug=body.slug, description=body.description)
    db.add(org)
    await db.flush()
    db.add(TenantGroupMapping(
        org_id=org.id,
        ad_group=body.owner_group,
        role="owner",
        created_by=current.user.id,
    ))
    await db.flush()
    await db.refresh(org)
    return _ws_out(org, "owner")


@router.get("/workspaces/current", response_model=WorkspaceOut)
async def get_current_workspace(
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    return _ws_out(ctx.workspace, ctx.role)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _require_membership(workspace_id, current, db, minimum="admin")
    org = membership.org
    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description
    await db.flush()
    await db.refresh(org)
    return _ws_out(org, membership.role)


@router.get(
    "/workspaces/{workspace_id}/group-mappings",
    response_model=list[GroupMappingOut],
)
async def list_group_mappings(
    workspace_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(workspace_id, current, db)
    result = await db.execute(
        select(TenantGroupMapping)
        .where(TenantGroupMapping.org_id == workspace_id)
        .order_by(TenantGroupMapping.created_at)
    )
    return result.scalars().all()


@router.post(
    "/workspaces/{workspace_id}/group-mappings",
    response_model=GroupMappingOut,
    status_code=201,
)
async def create_group_mapping(
    workspace_id: uuid.UUID,
    body: GroupMappingCreate,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(workspace_id, current, db, minimum="admin")
    dup = await db.execute(
        select(TenantGroupMapping).where(
            TenantGroupMapping.org_id == workspace_id,
            TenantGroupMapping.ad_group == body.ad_group,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"AD group '{body.ad_group}' is already mapped in this workspace",
        )
    mapping = TenantGroupMapping(
        org_id=workspace_id,
        ad_group=body.ad_group,
        role=body.role,
        created_by=current.user.id,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)
    return mapping


@router.delete(
    "/workspaces/{workspace_id}/group-mappings/{mapping_id}",
    status_code=204,
)
async def delete_group_mapping(
    workspace_id: uuid.UUID,
    mapping_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(workspace_id, current, db, minimum="admin")
    mapping = await db.get(TenantGroupMapping, mapping_id)
    if not mapping or mapping.org_id != workspace_id:
        raise HTTPException(status_code=404, detail="Mapping not found")

    # Never delete the last owner mapping — the workspace would become orphaned.
    if mapping.role == "owner":
        owners = await db.execute(
            select(TenantGroupMapping).where(
                TenantGroupMapping.org_id == workspace_id,
                TenantGroupMapping.role == "owner",
            )
        )
        if len(owners.scalars().all()) <= 1:
            raise HTTPException(
                status_code=422,
                detail="Cannot remove the last owner group mapping for a workspace",
            )

    await db.delete(mapping)
    await db.flush()
