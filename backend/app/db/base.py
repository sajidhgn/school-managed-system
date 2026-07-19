"""SQLAlchemy declarative base and metadata conventions.

WHY THIS FILE EXISTS
    Every ORM model must inherit from one `Base` so that a single `MetaData` object
    knows about every table. Alembic's autogenerate compares that MetaData against
    the live database -- if a model is not reachable from this Base, its table will
    silently never be migrated.

RESPONSIBILITY
    Define `Base`, the shared naming convention, and the default table-name rule.

INTERACTIONS
    * Every model in `app/modules/*/models.py` inherits from `Base`.
    * `alembic/env.py` imports `Base.metadata` as its migration target.

DEVIATION FROM THE SKILL PLAYBOOK
    The playbook uses `declarative_base()` from `sqlalchemy.ext.declarative`. That
    import path is removed in SQLAlchemy 2.x. The modern form is a `DeclarativeBase`
    subclass, which additionally gives real typing via `Mapped[...]`.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, declared_attr

# ---------------------------------------------------------------------------
# Naming convention -- do not change after the first migration ships.
#
# WHY THIS MATTERS: without it, PostgreSQL invents constraint names like
# `students_school_id_fkey1`. Those names differ between environments, so
# Alembic cannot reliably DROP them and your downgrade migrations break. Fixing
# the convention up front makes every constraint name deterministic and every
# migration reversible.
# ---------------------------------------------------------------------------
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

_CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    metadata = metadata

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """Derive `StudentEnrollment` -> `student_enrollments`.

        Convention over configuration: table names are plural snake_case. A model
        may still override `__tablename__` explicitly when the plural is irregular.
        """
        snake = _CAMEL_TO_SNAKE.sub("_", cls.__name__).lower()
        return snake if snake.endswith("s") else f"{snake}s"

    def __repr__(self) -> str:
        """Readable repr for debugging, showing only the primary key."""
        pk: Any = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"
