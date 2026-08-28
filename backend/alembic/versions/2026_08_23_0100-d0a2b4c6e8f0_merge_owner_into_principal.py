"""merge owner into principal

Revision ID: d0a2b4c6e8f0
Revises: c9f1a3b5d7e9
Create Date: 2026-08-23 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    The product used to model the top of an organization as two roles: an org-level
    `owner` (billing, campuses, everything) and a school-level `principal` (one
    campus, no billing). The founder was auto-granted both -- an org-level owner
    membership at signup, plus a school-scoped principal membership on their first
    school -- which listed one human twice in Members and gave them two entries in
    the context switcher for strictly less authority on the second.

    There is now ONE top role, `principal`, and it is org-level. This migration moves
    existing data onto that shape.

WHAT IT DOES, AND WHAT IT COSTS
    1. Every org-level `owner` role becomes `principal`. Its permission grants are
       untouched: `owner` already held the entire catalog, which is exactly what
       `principal` holds now. Nobody gains or loses a permission.

    2. The founder's redundant school-scoped principal membership is soft-deleted.
       They keep the org-level one, which already reaches that school.

    3. A school-level `principal` role that someone ELSE still holds is a real
       appointment, so it is preserved rather than dropped -- it becomes an ordinary
       custom role (`campus_principal`, "Campus Principal", editable, non-system)
       with its permissions unchanged. That member's access is identical the moment
       after this runs; the role is simply no longer platform-managed, and a
       principal can now edit or delete it like any other custom role.

    4. School-level `principal` roles nobody holds are deleted. New schools no longer
       seed one.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d0a2b4c6e8f0"
down_revision: str | None = "c9f1a3b5d7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRINCIPAL_DESCRIPTION = (
    "Runs the organization: billing, campuses, staff, roles and all school data."
)
OWNER_DESCRIPTION = "Owns billing and the organization. Can create schools and appoint principals."
OLD_PRINCIPAL_DESCRIPTION = (
    "Runs one school: staff, roles, invitations and all school data. No billing rights."
)


def upgrade() -> None:
    # --- 1. The org-level owner role becomes the principal role. --------------
    #
    # Permissions are deliberately not touched: `owner` was seeded with the full
    # catalog and `principal` is seeded with the full catalog, so the grants already
    # match. `permissions_version` therefore stays put -- bumping it would evict
    # every cached permission set to re-load an identical one.
    op.execute(
        f"""
        UPDATE roles
           SET code = 'principal',
               name = 'Principal',
               description = '{PRINCIPAL_DESCRIPTION}'
         WHERE code = 'owner'
           AND school_id IS NULL
        """
    )

    # --- 2. Drop the founder's duplicate school-scoped principal membership. ---
    #
    # Soft delete, matching how the application removes memberships: the row stays
    # for the audit trail and the partial unique index stops counting it.
    op.execute(
        """
        UPDATE memberships AS m
           SET deleted_at = now()
          FROM organizations AS o, roles AS r
         WHERE m.organization_id = o.id
           AND m.role_id = r.id
           AND m.user_id = o.owner_user_id
           AND m.school_id IS NOT NULL
           AND r.code = 'principal'
           AND r.school_id IS NOT NULL
           AND m.deleted_at IS NULL
        """
    )

    # --- 3. A campus principal someone else still holds keeps their access. ----
    #
    # The role survives as an ordinary custom role rather than being deleted out from
    # under a live member. `is_system = false` is what makes that honest: the platform
    # no longer seeds or maintains it.
    op.execute(
        """
        UPDATE roles
           SET code = 'campus_principal',
               name = 'Campus Principal',
               is_system = false,
               is_editable = true
         WHERE code = 'principal'
           AND school_id IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM memberships m
                WHERE m.role_id = roles.id
                  AND m.deleted_at IS NULL
           )
        """
    )

    # --- 4. Delete the school-level principal roles nobody holds. --------------
    #
    # `memberships.role_id` is ON DELETE RESTRICT, so the soft-deleted rows from
    # step 2 still pin these roles. Repoint them at the organization's principal role
    # first: the unique index on memberships is partial (`deleted_at IS NULL`), so a
    # dead row can be repointed without colliding with the live one, and the audit
    # trail keeps a resolvable `actor_membership_id`.
    op.execute(
        """
        UPDATE memberships AS m
           SET role_id = org_role.id
          FROM roles AS r, roles AS org_role
         WHERE m.role_id = r.id
           AND r.code = 'principal'
           AND r.school_id IS NOT NULL
           AND m.deleted_at IS NOT NULL
           AND org_role.organization_id = m.organization_id
           AND org_role.school_id IS NULL
           AND org_role.code = 'principal'
        """
    )
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE role_id IN (
             SELECT id FROM roles WHERE code = 'principal' AND school_id IS NOT NULL
         )
        """
    )
    op.execute("DELETE FROM roles WHERE code = 'principal' AND school_id IS NOT NULL")


def downgrade() -> None:
    """Restore the two-role naming. Best effort -- see the caveat below.

    The org-level role goes back to `owner`, and any `campus_principal` role goes back
    to a locked system `principal`. What CANNOT be restored is the founder's duplicate
    school-scoped membership: step 2 soft-deleted it and step 4 repointed it at the
    org-level role, so the original (school, role) pairing is gone. After a downgrade
    the founder holds only their org-level membership, which is a strictly smaller set
    of rows than before -- and no less access, since that membership already spans
    every school.
    """
    op.execute(
        f"""
        UPDATE roles
           SET code = 'principal',
               name = 'Principal',
               description = '{OLD_PRINCIPAL_DESCRIPTION}',
               is_system = true,
               is_editable = false
         WHERE code = 'campus_principal'
           AND school_id IS NOT NULL
        """
    )
    op.execute(
        f"""
        UPDATE roles
           SET code = 'owner',
               name = 'Owner',
               description = '{OWNER_DESCRIPTION}'
         WHERE code = 'principal'
           AND school_id IS NULL
        """
    )
