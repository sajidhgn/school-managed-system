"""API v1 aggregate router.

WHY THIS FILE EXISTS
    One place that assembles every module's router into the public v1 surface.
    `main.py` mounts exactly one router and therefore never needs editing when a
    module is added -- new modules are registered here, in one line each.

RESPONSIBILITY
    Composition only. No handlers, no logic. It decides URL prefixes and OpenAPI tag
    grouping (which becomes the section ordering in Swagger).

INTERACTIONS
    Imports each `app/modules/<module>/router.py` and mounts it under its prefix.
    Mounted by `main.py` at `settings.API_V1_PREFIX`.

WHY VERSION THE API AT ALL
    The Next.js frontend, the marketing site and any future integrations deploy
    independently of this backend. A URL version segment lets us ship a breaking
    change as /api/v2 while /api/v1 keeps serving existing clients during migration.

=============================================================================
THREE AUTH POSTURES, MOUNTED DELIBERATELY APART
=============================================================================
    * `/public/*` and `/invitations/*` and `/webhooks/*` -- UNAUTHENTICATED by
      design. The pricing page has no user; an invitee has no account yet; a payment
      gateway has no session.
    * `/platform/*` -- platform operators only, gated on the token's `typ` claim.
    * everything else -- tenant members, gated by `require(...)` per route.

    Grouping them explicitly means an endpoint cannot end up in the unauthenticated
    set by accident, which is the failure mode that matters most here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.academics.router import router as classes_router
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import public_router as public_plans_router
from app.modules.billing.router import router as billing_router
from app.modules.billing.router import webhook_router
from app.modules.invitations.router import public_router as public_invitations_router
from app.modules.invitations.router import school_router as school_invitations_router
from app.modules.platform_admin.router import router as platform_router
from app.modules.rbac.audit_router import router as audit_router
from app.modules.rbac.router import members_router, permissions_router, roles_router
from app.modules.students.router import router as students_router
from app.modules.tenancy.router import org_router, schools_router

api_router = APIRouter()

# --- Unauthenticated -------------------------------------------------------
api_router.include_router(public_plans_router, prefix="/public", tags=["Public"])
api_router.include_router(public_invitations_router, prefix="/invitations", tags=["Invitations"])
api_router.include_router(webhook_router, prefix="/webhooks", tags=["Webhooks"])

# --- Platform console ------------------------------------------------------
api_router.include_router(platform_router, prefix="/platform", tags=["Platform"])

# --- Identity --------------------------------------------------------------
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])

# --- Organization & billing ------------------------------------------------
api_router.include_router(org_router, prefix="/org", tags=["Organization"])
api_router.include_router(billing_router, prefix="/billing", tags=["Billing"])

# --- Schools ---------------------------------------------------------------
# Four routers share the `/schools` prefix, each owning a different sub-path
# (`/{id}/roles`, `/{id}/members`, `/{id}/invitations`, `/{id}/audit-logs`). They are
# separate modules because they are separate concerns; FastAPI merges them into one
# coherent path tree, and the OpenAPI tags keep them readable in Swagger.
api_router.include_router(schools_router, prefix="/schools", tags=["Schools"])
api_router.include_router(roles_router, prefix="/schools", tags=["Roles & permissions"])
api_router.include_router(members_router, prefix="/schools", tags=["Members"])
api_router.include_router(school_invitations_router, prefix="/schools", tags=["Invitations"])
api_router.include_router(audit_router, prefix="/schools", tags=["Audit"])

# The permission catalog is global, not school-scoped -- it describes what the
# software can do, which is identical for every customer.
api_router.include_router(permissions_router, prefix="/permissions", tags=["Roles & permissions"])

# --- Academic modules ------------------------------------------------------
# Out of scope for the core spec (§13) but already built, now re-keyed onto
# organization_id + school_id and the shared permission catalog.
api_router.include_router(classes_router, prefix="/classes", tags=["Classes & Sections"])
api_router.include_router(students_router, prefix="/students", tags=["Students"])
