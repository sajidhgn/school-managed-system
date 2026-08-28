"""Guardian registry business rules -- what school staff may do to parent records.

WHY THIS FILE EXISTS
    Everything that decides what is ALLOWED when a school records a parent: that one
    phone number is one person, that a child has at most one primary contact, that a
    guardian still holding children cannot be deleted, and that re-pointing a login
    at a different handset is a credential change rather than a profile edit.

INTERACTIONS
    * `router.py` translates HTTP; this layer never imports fastapi.
    * `auth_service.py` owns the login flow and shares only the models.
    * `students.service` is untouched: the legacy `guardian_*` columns on `students`
      remain as the denormalised fallback for schools that have not migrated. See
      `sync_legacy_student_columns` for how the two are kept from disagreeing.

=============================================================================
THE IDENTITY IS FOUND OR CREATED, NEVER DUPLICATED
=============================================================================
    `register` normalises the phone, then looks for an existing identity. Three
    outcomes, and getting them right is the whole value of the module:

      * NO IDENTITY -> create one, create this organization's guardian record.
      * IDENTITY EXISTS, this organization already has a record -> 409. The clerk is
        re-registering someone the school already holds, and silently creating a
        second record is the bug this table replaced.
      * IDENTITY EXISTS, another organization's -> attach. This is the father with a
        child at a rival group; we create OUR record pointing at HIS identity, and
        neither organization can see the other's row (RLS).

    The third case is why the endpoint returns 201 with no hint that the person was
    already known: telling a clerk at School A "this parent already exists" would leak
    that a specific phone number has a child somewhere else on the platform.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.config import Settings, get_settings
from app.core.context import get_school_id, require_organization_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.phone import normalise_phone
from app.modules.guardians.models import (
    Guardian,
    GuardianIdentity,
    GuardianRelationship,
    GuardianStudent,
)
from app.modules.guardians.repository import (
    GuardianIdentityRepository,
    GuardianRepository,
    GuardianStudentRepository,
)
from app.modules.guardians.schemas import (
    GuardianCreate,
    GuardianDetail,
    GuardianLinkCreate,
    GuardianLinkUpdate,
    GuardianRead,
    GuardianUpdate,
    LinkedStudentRead,
    StudentGuardianRead,
)
from app.modules.students.models import Student

logger = get_logger(__name__)


class GuardianService:
    """Guardian records, their student links, and the identities behind them."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.guardians = GuardianRepository(session)
        self.links = GuardianStudentRepository(session)
        self.identities = GuardianIdentityRepository(session)

    # -- helpers ------------------------------------------------------------

    def _normalise(self, raw: str) -> str:
        """Canonicalise a phone with this deployment's defaults.

        Centralised so that registration, lookup and login all produce the same
        string. A phone normalised one way on write and another on read is a login
        that fails for exactly the parents whose numbers were typed nationally.
        """
        return normalise_phone(
            raw,
            default_calling_code=self.settings.DEFAULT_COUNTRY_CALLING_CODE,
            trunk_prefix=self.settings.NATIONAL_TRUNK_PREFIX,
        )

    async def _get_student(self, student_id: UUID) -> Student:
        """Load a student inside the caller's tenant and campus, or 404.

        Goes through the tenant-bound session, so a student in another organization
        is filtered out by RLS and reads as absent -- a 404, never a 403. A 403 would
        confirm the child exists, which is itself a cross-tenant leak.
        """
        student = await self.session.get(Student, student_id)
        if student is None or student.deleted_at is not None:
            raise NotFoundError("Student not found.")
        if (school_id := get_school_id()) is not None and student.school_id != school_id:
            raise NotFoundError("Student not found.")
        return student

    async def get(self, guardian_id: UUID) -> Guardian:
        guardian = await self.guardians.get_with_identity(guardian_id)
        if guardian is None:
            raise NotFoundError("Guardian not found.")
        # A school-scoped caller may only reach a guardian who has a child at their
        # campus. `get_with_identity` deliberately does not apply that -- it is a plain
        # primary-key load, and the org-level principal needs it unfiltered -- so the
        # scope check happens here, once, on the read path every mutation goes through.
        if (campus := self.guardians.campus_predicate()) is not None:
            visible = await self.session.execute(
                select(Guardian.id).where(Guardian.id == guardian_id, campus).limit(1)
            )
            if visible.first() is None:
                raise NotFoundError("Guardian not found.")
        return guardian

    # -- registry -----------------------------------------------------------

    async def register(
        self, payload: GuardianCreate, *, actor_id: UUID | None = None
    ) -> GuardianRead:
        """Create this organization's record for a guardian. See the module docstring."""
        phone = self._normalise(payload.phone)

        identity = await self.identities.get_by_phone(phone)
        if identity is None:
            identity = await self.identities.create(
                phone=phone,
                full_name=payload.full_name,
                email=payload.email,
                preferred_locale=payload.preferred_locale or "en",
            )
        elif payload.email and identity.email is None:
            # Fill a gap, never overwrite. Another organization may have recorded a
            # different address for the same person and neither school's clerk is
            # authoritative over the other's.
            identity.email = payload.email

        existing = await self.guardians.get_by_identity(identity.id)
        if existing is not None:
            raise ConflictError(
                f"{existing.full_name} is already registered with this phone number.",
                details={"guardian_id": str(existing.id)},
            )

        guardian = await self.guardians.create(
            organization_id=require_organization_id(),
            # The campus whose front office typed this in. NOT a scope key -- see the
            # column's docstring -- but it is what makes the record visible to its own
            # registrar before the first child is linked.
            registered_school_id=get_school_id(),
            identity_id=identity.id,
            full_name=payload.full_name,
            cnic=payload.cnic,
            occupation=payload.occupation,
            address=payload.address,
            alternate_phone=self._normalise(payload.alternate_phone)
            if payload.alternate_phone
            else None,
            notes=payload.notes,
        )

        await record_audit(
            self.session,
            organization_id=guardian.organization_id,
            school_id=get_school_id(),
            action=AuditAction.GUARDIAN_REGISTERED,
            actor_user_id=actor_id,
            entity_type="guardian",
            entity_id=guardian.id,
            # The phone is NOT recorded in the audit payload. Audit rows are read by
            # more people than the guardian record is, and a contact number is the
            # single most sensitive field here.
            after={"full_name": guardian.full_name, "identity_id": str(identity.id)},
        )
        logger.info("guardian_registered", guardian_id=str(guardian.id))
        return self._to_read(guardian, identity, student_count=0)

    async def list_guardians(
        self,
        *,
        params: PageParams,
        sort: SortParams,
        search: str | None = None,
        student_id: UUID | None = None,
    ) -> Page[GuardianRead]:
        rows, total = await self.guardians.list_for_scope(
            params=params, sort=sort, search=search, student_id=student_id
        )
        counts = await self.guardians.student_counts([g.id for g in rows])
        items = [self._to_read(g, g.identity, counts.get(g.id, 0)) for g in rows]
        return Page.create(items, total, params)

    async def detail(self, guardian_id: UUID) -> GuardianDetail:
        guardian = await self.get(guardian_id)
        links = await self.links.list_for_guardian(guardian_id)
        base = self._to_read(guardian, guardian.identity, len(links))
        return GuardianDetail(
            **base.model_dump(),
            students=[self._link_to_read(link) for link in links],
        )

    async def update(
        self, guardian_id: UUID, payload: GuardianUpdate, *, actor_id: UUID | None = None
    ) -> GuardianRead:
        guardian = await self.get(guardian_id)
        values = payload.model_dump(exclude_unset=True)

        # `preferred_locale` lives on the IDENTITY, not on the record -- it is a
        # property of the reader, and a parent who asked for Urdu at one campus should
        # not get English SMS from the other. Split out before the record update so it
        # is not passed to a column that does not exist.
        locale = values.pop("preferred_locale", None)
        if locale:
            guardian.identity.preferred_locale = locale

        email = values.pop("email", "__unset__")
        if email != "__unset__":
            guardian.identity.email = email

        if (alternate := values.get("alternate_phone")) is not None:
            values["alternate_phone"] = self._normalise(alternate)

        before = {"full_name": guardian.full_name}
        updated = await self.guardians.update(guardian, **values)

        await record_audit(
            self.session,
            organization_id=updated.organization_id,
            school_id=get_school_id(),
            action=AuditAction.GUARDIAN_UPDATED,
            actor_user_id=actor_id,
            entity_type="guardian",
            entity_id=updated.id,
            before=before,
            after={"full_name": updated.full_name},
        )
        count = (await self.guardians.student_counts([updated.id])).get(updated.id, 0)
        return self._to_read(updated, updated.identity, count)

    async def change_phone(
        self, guardian_id: UUID, raw_phone: str, *, actor_id: UUID | None = None
    ) -> GuardianRead:
        """Re-point this record at a different handset.

        =====================================================================
        THIS IS A CREDENTIAL CHANGE, NOT A PROFILE EDIT
        =====================================================================
            The phone is the login identifier. Moving it hands portal access to
            whoever holds the new number and takes it from whoever holds the old one,
            so it is separately permissioned (`guardian:portal`), separately audited,
            and separately shaped in the API.

            IT MOVES THIS ORGANIZATION'S RECORD, NOT THE IDENTITY. Editing
            `GuardianIdentity.phone` in place would silently re-point every OTHER
            organization's record for the same person at a handset only this school
            was told about -- a cross-tenant credential change performed by a clerk
            who cannot even see the other tenant. The record is instead attached to
            the identity that owns the new number, creating it if necessary.
        """
        guardian = await self.get(guardian_id)
        phone = self._normalise(raw_phone)

        if guardian.identity.phone == phone:
            return self._to_read(guardian, guardian.identity, 0)

        target = await self.identities.get_by_phone(phone)
        if target is None:
            target = await self.identities.create(
                phone=phone,
                full_name=guardian.full_name,
                email=guardian.identity.email,
                preferred_locale=guardian.identity.preferred_locale,
            )
        elif (clash := await self.guardians.get_by_identity(target.id)) is not None:
            raise ConflictError(
                f"{clash.full_name} is already registered with that phone number.",
                details={"guardian_id": str(clash.id)},
            )

        previous_identity_id = guardian.identity_id
        guardian.identity_id = target.id
        guardian.identity = target
        await self.session.flush()

        await record_audit(
            self.session,
            organization_id=guardian.organization_id,
            school_id=get_school_id(),
            action=AuditAction.GUARDIAN_PHONE_CHANGED,
            actor_user_id=actor_id,
            entity_type="guardian",
            entity_id=guardian.id,
            # Identity ids, not numbers. The trail must record that the login moved and
            # who moved it, without printing either handset into a log a hundred people
            # can read.
            before={"identity_id": str(previous_identity_id)},
            after={"identity_id": str(target.id)},
        )
        logger.info("guardian_phone_changed", guardian_id=str(guardian.id))
        count = (await self.guardians.student_counts([guardian.id])).get(guardian.id, 0)
        return self._to_read(guardian, target, count)

    async def set_portal_access(
        self, guardian_id: UUID, *, enabled: bool, actor_id: UUID | None = None
    ) -> GuardianRead:
        """Open or close the parent portal for this organization's records."""
        guardian = await self.get(guardian_id)
        if guardian.portal_enabled == enabled:
            count = (await self.guardians.student_counts([guardian.id])).get(guardian.id, 0)
            return self._to_read(guardian, guardian.identity, count)

        updated = await self.guardians.update(guardian, portal_enabled=enabled)
        await record_audit(
            self.session,
            organization_id=updated.organization_id,
            school_id=get_school_id(),
            action=AuditAction.GUARDIAN_PORTAL_ENABLED
            if enabled
            else AuditAction.GUARDIAN_PORTAL_DISABLED,
            actor_user_id=actor_id,
            entity_type="guardian",
            entity_id=updated.id,
            after={"portal_enabled": enabled},
        )
        count = (await self.guardians.student_counts([updated.id])).get(updated.id, 0)
        return self._to_read(updated, updated.identity, count)

    async def remove(self, guardian_id: UUID, *, actor_id: UUID | None = None) -> None:
        """Soft-delete a guardian record.

        Refuses while children are still linked, rather than cascading. The FK would
        happily remove every link, and the emergency contact for four children would
        disappear on one mis-click with nothing in the UI to say so. Unlinking first
        is one extra step and makes the loss deliberate.
        """
        guardian = await self.get(guardian_id)
        links = await self.links.list_for_guardian(guardian_id)
        if links:
            raise ConflictError(
                f"{guardian.full_name} is still linked to {len(links)} student(s). "
                "Unlink them before removing this guardian."
            )
        await self.guardians.soft_delete(guardian)
        await record_audit(
            self.session,
            organization_id=guardian.organization_id,
            school_id=get_school_id(),
            action=AuditAction.GUARDIAN_REMOVED,
            actor_user_id=actor_id,
            entity_type="guardian",
            entity_id=guardian.id,
        )
        logger.info("guardian_removed", guardian_id=str(guardian_id))

    # -- links --------------------------------------------------------------

    async def link_student(
        self, guardian_id: UUID, payload: GuardianLinkCreate, *, actor_id: UUID | None = None
    ) -> LinkedStudentRead:
        guardian = await self.get(guardian_id)
        student = await self._get_student(payload.student_id)

        if await self.links.get_link(guardian_id, student.id) is not None:
            raise ConflictError(f"{guardian.full_name} is already linked to this student.")

        self._validate_relationship(payload.relationship_type, payload.relationship_label)
        if payload.is_primary_contact:
            await self._release_primary(student.id, actor_id=actor_id)

        link = await self.links.create(
            organization_id=guardian.organization_id,
            # From the STUDENT, not from the request context. A link inherits the
            # child's campus so it can never end up scoped to a school the child does
            # not attend -- which would make the child invisible on their own campus's
            # contact list.
            school_id=student.school_id,
            guardian_id=guardian.id,
            student_id=student.id,
            relationship_type=payload.relationship_type,
            relationship_label=payload.relationship_label,
            is_primary_contact=payload.is_primary_contact,
            is_emergency_contact=payload.is_emergency_contact,
            can_pickup=payload.can_pickup,
            receives_notifications=payload.receives_notifications,
            can_view_results=payload.can_view_results,
        )
        link.student = student

        await record_audit(
            self.session,
            organization_id=guardian.organization_id,
            school_id=student.school_id,
            action=AuditAction.GUARDIAN_LINKED,
            actor_user_id=actor_id,
            # `entity_type` is the STUDENT, not the link. The question this trail
            # answers is "who was given access to this child, and when" -- an audit
            # filtered by a join-table id cannot answer it.
            entity_type="student",
            entity_id=student.id,
            after={
                "guardian_id": str(guardian.id),
                "relationship": payload.relationship_type.value,
                "can_pickup": payload.can_pickup,
                "is_primary_contact": payload.is_primary_contact,
            },
        )
        return self._link_to_read(link)

    async def update_link(
        self,
        guardian_id: UUID,
        student_id: UUID,
        payload: GuardianLinkUpdate,
        *,
        actor_id: UUID | None = None,
    ) -> LinkedStudentRead:
        await self.get(guardian_id)
        link = await self.links.get_link(guardian_id, student_id)
        if link is None:
            raise NotFoundError("This guardian is not linked to that student.")

        values = payload.model_dump(exclude_unset=True)
        relationship = values.get("relationship_type", link.relationship_type)
        label = values.get("relationship_label", link.relationship_label)
        self._validate_relationship(relationship, label)

        if values.get("is_primary_contact") is True and not link.is_primary_contact:
            await self._release_primary(student_id, actor_id=actor_id)

        before = {
            "can_pickup": link.can_pickup,
            "is_primary_contact": link.is_primary_contact,
            "can_view_results": link.can_view_results,
        }
        updated = await self.links.update(link, **values)
        student = await self._get_student(student_id)
        updated.student = student

        await record_audit(
            self.session,
            organization_id=updated.organization_id,
            school_id=updated.school_id,
            action=AuditAction.GUARDIAN_LINK_UPDATED,
            actor_user_id=actor_id,
            entity_type="student",
            entity_id=student_id,
            before=before,
            after={
                "guardian_id": str(guardian_id),
                "can_pickup": updated.can_pickup,
                "is_primary_contact": updated.is_primary_contact,
                "can_view_results": updated.can_view_results,
            },
        )
        return self._link_to_read(updated)

    async def unlink_student(
        self, guardian_id: UUID, student_id: UUID, *, actor_id: UUID | None = None
    ) -> None:
        await self.get(guardian_id)
        link = await self.links.get_link(guardian_id, student_id)
        if link is None:
            raise NotFoundError("This guardian is not linked to that student.")

        await self.links.soft_delete(link)
        await record_audit(
            self.session,
            organization_id=link.organization_id,
            school_id=link.school_id,
            action=AuditAction.GUARDIAN_UNLINKED,
            actor_user_id=actor_id,
            entity_type="student",
            entity_id=student_id,
            before={"guardian_id": str(guardian_id)},
        )

    async def list_for_student(self, student_id: UUID) -> list[StudentGuardianRead]:
        """The contact card for one child: every guardian, primary first."""
        await self._get_student(student_id)
        links = await self.links.list_for_student(student_id)
        return [
            StudentGuardianRead(
                link_id=link.id,
                guardian_id=link.guardian_id,
                identity_id=link.guardian.identity_id,
                full_name=link.guardian.full_name,
                phone=link.guardian.identity.phone,
                alternate_phone=link.guardian.alternate_phone,
                email=link.guardian.identity.email,
                cnic=link.guardian.cnic,
                relationship_type=link.relationship_type,
                relationship_label=link.relationship_label,
                is_primary_contact=link.is_primary_contact,
                is_emergency_contact=link.is_emergency_contact,
                can_pickup=link.can_pickup,
                receives_notifications=link.receives_notifications,
                can_view_results=link.can_view_results,
                portal_enabled=link.guardian.portal_enabled,
            )
            for link in links
        ]

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _validate_relationship(relationship: GuardianRelationship, label: str | None) -> None:
        """OTHER must carry a printable label; the others must not invent one.

        Mirrors the CHECK constraint on the table. Duplicated deliberately: the
        constraint is the guarantee, and this is the error message. A raw constraint
        violation reaches the client as a 500 and tells a clerk nothing.
        """
        if relationship is GuardianRelationship.OTHER and not label:
            raise ValidationError(
                "Describe the relationship when choosing 'Other'.",
                code="RELATIONSHIP_LABEL_REQUIRED",
            )

    async def _release_primary(self, student_id: UUID, *, actor_id: UUID | None) -> None:
        """Demote whoever currently holds primary contact for this child.

        Read-then-write rather than letting the partial unique index reject the
        insert: the constraint is the safety net, but a 500 on "make the father the
        primary contact" is not an answer. Recorded in the audit trail because losing
        primary contact is a change the demoted parent would want explained.
        """
        current = await self.links.current_primary(student_id)
        if current is None:
            return
        await self.links.update(current, is_primary_contact=False)
        await record_audit(
            self.session,
            organization_id=current.organization_id,
            school_id=current.school_id,
            action=AuditAction.GUARDIAN_LINK_UPDATED,
            actor_user_id=actor_id,
            entity_type="student",
            entity_id=student_id,
            before={"guardian_id": str(current.guardian_id), "is_primary_contact": True},
            after={"guardian_id": str(current.guardian_id), "is_primary_contact": False},
        )

    @staticmethod
    def _to_read(
        guardian: Guardian, identity: GuardianIdentity, student_count: int
    ) -> GuardianRead:
        return GuardianRead(
            id=guardian.id,
            identity_id=guardian.identity_id,
            phone=identity.phone,
            full_name=guardian.full_name,
            email=identity.email,
            cnic=guardian.cnic,
            occupation=guardian.occupation,
            address=guardian.address,
            alternate_phone=guardian.alternate_phone,
            portal_enabled=guardian.portal_enabled,
            notes=guardian.notes,
            preferred_locale=identity.preferred_locale,
            identity_status=identity.status.value,
            last_login_at=identity.last_login_at,
            student_count=student_count,
            created_at=guardian.created_at,
            updated_at=guardian.updated_at,
        )

    @staticmethod
    def _link_to_read(link: GuardianStudent) -> LinkedStudentRead:
        student = link.student
        return LinkedStudentRead(
            link_id=link.id,
            student_id=link.student_id,
            school_id=link.school_id,
            admission_number=student.admission_number,
            full_name=f"{student.first_name} {student.last_name}",
            section_id=student.section_id,
            status=student.status.value,
            relationship_type=link.relationship_type,
            relationship_label=link.relationship_label,
            is_primary_contact=link.is_primary_contact,
            is_emergency_contact=link.is_emergency_contact,
            can_pickup=link.can_pickup,
            receives_notifications=link.receives_notifications,
            can_view_results=link.can_view_results,
        )


def guardian_payload(link: GuardianStudent) -> dict[str, Any]:
    """Reusable contact projection for other modules (attendance alerts, fees).

    Exposed as a function rather than a method so a notification job can build a
    recipient list without instantiating the whole service and its four repositories.
    """
    return {
        "guardian_id": str(link.guardian_id),
        "student_id": str(link.student_id),
        "phone": link.guardian.identity.phone,
        "locale": link.guardian.identity.preferred_locale,
        "receives_notifications": link.receives_notifications,
    }
