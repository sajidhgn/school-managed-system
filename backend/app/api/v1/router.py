"""API v1 aggregate router.

WHY THIS FILE EXISTS
    One place that assembles every module's router into the public v1 surface.
    `main.py` mounts exactly one router and therefore never needs editing when a
    module is added -- new modules are registered here, in one line each.

RESPONSIBILITY
    Composition only. No handlers, no logic. It decides URL prefixes and OpenAPI
    tag grouping (which becomes the section ordering in Swagger).

INTERACTIONS
    Imports each `app/modules/<module>/router.py` and mounts it under its prefix.
    Mounted by `main.py` at `settings.API_V1_PREFIX`.

WHY VERSION THE API AT ALL
    The Next.js frontend, the parent mobile app and any future integrations deploy
    independently of this backend. A URL version segment lets us ship a breaking
    change as /api/v2 while /api/v1 keeps serving existing clients during migration.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.tenancy.router import router as tenancy_router

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Module routers are registered here as each module is implemented.
# The order below is the delivery roadmap order and also controls the section
# ordering in the generated Swagger docs.
# ---------------------------------------------------------------------------

# Module 1 -- Tenancy & Access Control
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(tenancy_router, prefix="/schools", tags=["Schools"])

# Module 2 -- Student Information System
# api_router.include_router(students_router, prefix="/students", tags=["Students"])
# api_router.include_router(classes_router,  prefix="/classes",  tags=["Classes & Sections"])
#
# Module 3 -- Academics & Daily Ops
# api_router.include_router(attendance_router, prefix="/attendance", tags=["Attendance"])
# api_router.include_router(timetable_router,  prefix="/timetable",  tags=["Timetable"])
#
# Module 4 -- Financials
# api_router.include_router(fees_router, prefix="/fees", tags=["Fees"])
#
# ... remaining modules per the roadmap.
