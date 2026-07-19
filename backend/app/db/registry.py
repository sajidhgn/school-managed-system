"""Model registry -- the single import that makes every table visible.

WHY THIS FILE EXISTS
    SQLAlchemy only knows about a model once its module has been imported. Alembic's
    autogenerate compares `Base.metadata` against the live database, so a model that
    was never imported is *absent* from the metadata -- and autogenerate will
    interpret its existing table as "not in the model" and generate a DROP TABLE.

    That failure mode is silent, destructive, and easy to hit. This module makes the
    import explicit and reviewable: adding a model means adding one line here.

RESPONSIBILITY
    Import every ORM model module. It defines nothing itself.

INTERACTIONS
    * `alembic/env.py` imports it before reading `Base.metadata`.
    * `tests/conftest.py` imports it before `create_all`.

RULE
    Every new `app/modules/<name>/models.py` MUST be added below in the same commit
    that creates it.
"""

from __future__ import annotations

from app.db.base import Base

# Module 1 -- Tenancy & Access Control
from app.modules.auth import models as auth_models
from app.modules.tenancy import models as tenancy_models

# ---------------------------------------------------------------------------
# Module 2 -- Student Information System
# from app.modules.students import models as student_models
#
# ... one line per module as it is implemented.
# ---------------------------------------------------------------------------

__all__ = ["Base", "auth_models", "tenancy_models"]
