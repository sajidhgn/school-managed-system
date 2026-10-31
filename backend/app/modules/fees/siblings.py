"""Sibling remission -- find families through their parents, propose, let staff apply.

WHY THIS FILE EXISTS
    A school gives a family's younger children a discount: the second child 10% off
    tuition, the third 15%, and so on. Until the guardian registry existed the only way
    to find a family was a surname, which is wrong for cousins who share one and for
    half-siblings who do not.

    Two children are SIBLINGS here when they share a father, mother or legal guardian
    in the registry. A grandparent, uncle or the neighbour who does the school run
    links children too, but not as a family that pays one set of fees, so those links
    are ignored. Families are joined transitively: half-brothers who each share one
    parent with a third child are one family, which is how a blended household
    actually pays.

RESPONSIBILITY
    The campus rule (`FeeSiblingRule`), a REVIEW of every family with a child at this
    campus, and APPLY, which turns chosen proposals into ordinary DISCOUNT
    arrangements through `FeeService.record_assignment`. Billing never reads anything
    here, so a mistyped guardian link can never change a bill without a person
    looking at it first.

THE ORDER
    The child in the family's HIGHEST CLASS pays in full; the next is the second
    child, and so on. Ties go to the earlier admission (`enrolled_on`, then the date
    the record was created). Only ACTIVE students placed in a section count -- an
    applicant or a child who left is not a sibling anyone is paying for.

ACROSS CAMPUSES
    The guardian record belongs to the organization, so a family with a son at the
    boys' campus and a daughter at the girls' campus is found as one. Positions are
    counted across the whole family; each campus applies its own rule to its own
    children. The review shows a sibling at another campus by name, class and campus
    only, because the person deciding needs to see why their child is "second".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.audit import AuditAction
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Section
from app.modules.fees.models import (
    FeeConcession,
    FeeSiblingRule,
    StudentFeeAssignment,
    StudentFeeAssignmentMode,
)
from app.modules.fees.schemas import (
    FeeSiblingRuleInput,
    FeeSiblingRuleRead,
    SiblingAction,
    SiblingApplyRequest,
    SiblingApplyResult,
    SiblingFamily,
    SiblingGuardian,
    SiblingMember,
    SiblingReview,
    SiblingSchemeRead,
    SiblingSkip,
    StudentFeeAssignmentInput,
)
from app.modules.fees.service import FeeService
from app.modules.guardians.models import Guardian, GuardianRelationship, GuardianStudent
from app.modules.students.models import Student, StudentStatus
from app.modules.tenancy.models import School

logger = get_logger(__name__)

PARENTAL = (
    GuardianRelationship.FATHER,
    GuardianRelationship.MOTHER,
    GuardianRelationship.LEGAL_GUARDIAN,
)
"""The relationships that make children one fee-paying family."""

_NEEDS_ACTION = frozenset(
    {SiblingAction.APPLY, SiblingAction.CHANGE, SiblingAction.REMOVE, SiblingAction.CONFLICT}
)


def _ordinal(position: int) -> str:
    suffix = (
        "th" if 10 <= position % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    )
    return f"{position}{suffix}"


@dataclass(slots=True)
class _Child:
    student_id: UUID
    name: str
    admission_number: str
    school_id: UUID
    campus_name: str
    class_name: str | None
    class_level: int | None
    section_name: str | None
    enrolled_on: date | None
    created_at: datetime

    @property
    def order_key(self) -> tuple[int, date, datetime, str]:
        return (
            -(self.class_level or 0),
            self.enrolled_on or date.max,
            self.created_at,
            str(self.student_id),
        )


@dataclass(slots=True)
class _Plan:
    """Everything one review works out, kept so `apply` acts on the same answer."""

    rule: FeeSiblingRule
    families: list[SiblingFamily] = field(default_factory=list)
    no_longer_eligible: list[SiblingMember] = field(default_factory=list)
    current: dict[UUID, StudentFeeAssignment] = field(default_factory=dict)
    """This campus's live arrangement on the rule's head, by student."""

    def campus_members(self) -> dict[UUID, SiblingMember]:
        members = {m.student_id: m for f in self.families for m in f.members if m.at_this_campus}
        members.update({m.student_id: m for m in self.no_longer_eligible})
        return members


class SiblingService:
    """The sibling rule, the family review, and applying it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.fees = FeeService(session)
        self.rules = self.fees.sibling_rules

    # =====================================================================
    # The rule
    # =====================================================================

    async def get_rule(self) -> FeeSiblingRuleRead | None:
        rule = await self.rules.get_current()
        return self._rule_read(rule) if rule else None

    async def set_rule(self, payload: FeeSiblingRuleInput, *, actor_id: UUID) -> FeeSiblingRuleRead:
        """Create or replace this campus's rule. Changes nothing on any child: the
        next review shows who it now proposes to move."""
        head = await self.fees.get_head(payload.head_id)
        if not head.is_active:
            raise ValidationError(f"Fee head '{head.name}' is inactive.", code="FEE_HEAD_INACTIVE")
        for concession_id in (
            payload.second_concession_id,
            payload.third_concession_id,
            payload.later_concession_id,
        ):
            if concession_id is None:
                continue
            # Resolved through the campus-scoped repository, so another campus's
            # scheme reads as absent and 404s here rather than at billing.
            concession = await self.fees.get_concession(concession_id)
            if not concession.is_active:
                raise ValidationError(
                    f"Concession '{concession.name}' is inactive.", code="CONCESSION_INACTIVE"
                )

        values = payload.model_dump()
        existing = await self.rules.get_current()
        if existing is None:
            rule = await self.rules.create(
                **values,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
            )
            before: dict[str, Any] | None = None
        else:
            before = self._audit_values(existing)
            rule = await self.rules.update(existing, **values)

        await self.fees._audit(
            AuditAction.FEE_SIBLING_RULE_SET,
            entity_type="fee_sibling_rule",
            entity_id=rule.id,
            actor_id=actor_id,
            before=before,
            after=self._audit_values(rule),
        )
        logger.info("fee_sibling_rule_set", rule_id=str(rule.id))
        saved = await self.rules.get_current()
        assert saved is not None
        return self._rule_read(saved)

    async def delete_rule(self, *, actor_id: UUID) -> None:
        """Stop proposing sibling discounts. Children already on a sibling scheme keep
        it; take them off from their own page."""
        rule = await self.rules.get_current()
        if rule is None:
            raise NotFoundError("This campus has no sibling rule.")
        before = self._audit_values(rule)
        await self.rules.hard_delete(rule.id)
        await self.fees._audit(
            AuditAction.FEE_SIBLING_RULE_DELETED,
            entity_type="fee_sibling_rule",
            entity_id=rule.id,
            actor_id=actor_id,
            before=before,
        )
        logger.info("fee_sibling_rule_deleted", rule_id=str(rule.id))

    # =====================================================================
    # The review
    # =====================================================================

    async def review(self, academic_year: str) -> SiblingReview:
        return self._review_read(academic_year, await self._plan(academic_year))

    async def apply(self, payload: SiblingApplyRequest, *, actor_id: UUID) -> SiblingApplyResult:
        """Do what the review proposes for the chosen children, worked out afresh.

        Each change is an ordinary arrangement write, audited like one typed on the
        student's page. A child the review would leave alone, or who is in conflict,
        is skipped with the reason rather than failing the batch.
        """
        plan = await self._plan(payload.academic_year)
        members = plan.campus_members()
        head = plan.rule.head

        wanted = list(dict.fromkeys(payload.student_ids))
        students = {
            s.id: s
            for s in (
                await self.session.execute(
                    select(Student).where(
                        Student.id.in_(wanted), Student.school_id == require_school_id()
                    )
                )
            ).scalars()
        }

        applied = changed = removed = 0
        skipped: list[SiblingSkip] = []
        for student_id in wanted:
            member = members.get(student_id)
            if member is None or student_id not in students:
                skipped.append(
                    SiblingSkip(
                        student_id=student_id,
                        reason="Not a child at this campus with a sibling discount to change.",
                    )
                )
                continue

            if member.action in (SiblingAction.APPLY, SiblingAction.CHANGE):
                assert member.proposed_concession_id is not None and member.position is not None
                await self.fees.record_assignment(
                    students[student_id],
                    head,
                    StudentFeeAssignmentInput(
                        head_id=head.id,
                        academic_year=payload.academic_year,
                        mode=StudentFeeAssignmentMode.DISCOUNT,
                        concession_id=member.proposed_concession_id,
                        note=f"Sibling discount: {_ordinal(member.position)} child",
                    ),
                    actor_id=actor_id,
                )
                if member.action is SiblingAction.APPLY:
                    applied += 1
                else:
                    changed += 1
            elif member.action is SiblingAction.REMOVE:
                await self.fees.drop_assignment(plan.current[student_id], actor_id=actor_id)
                removed += 1
            else:
                skipped.append(
                    SiblingSkip(
                        student_id=student_id,
                        reason=member.reason or "Nothing to change.",
                    )
                )

        logger.info(
            "fee_siblings_applied",
            applied=applied,
            changed=changed,
            removed=removed,
            skipped=len(skipped),
        )
        return SiblingApplyResult(
            applied=applied,
            changed=changed,
            removed=removed,
            skipped=skipped,
            review=await self.review(payload.academic_year),
        )

    async def _plan(self, academic_year: str) -> _Plan:
        rule = await self.rules.get_current()
        if rule is None:
            raise ValidationError(
                "Set up the sibling rule first: choose the fee head and the scheme for "
                "the second child.",
                code="SIBLING_RULE_MISSING",
            )
        school_id = require_school_id()
        plan = _Plan(rule=rule)

        links = await self._family_links(school_id)
        groups = self._group(links)
        children = await self._children({s for group in groups for s in group})
        campus_ids = {sid for sid, child in children.items() if child.school_id == school_id}

        plan.current = await self._current(academic_year, rule, campus_ids)

        guardians: dict[UUID, dict[UUID, tuple[str, set[GuardianRelationship]]]] = {}
        for guardian_id, student_id, relationship, guardian_name in links:
            per_student = guardians.setdefault(student_id, {})
            entry = per_student.setdefault(guardian_id, (guardian_name, set()))
            entry[1].add(relationship)

        families: list[SiblingFamily] = []
        in_family: set[UUID] = set()
        for group in groups:
            ordered = sorted(
                (children[s] for s in group if s in children), key=lambda c: c.order_key
            )
            if len(ordered) < 2 or not any(c.school_id == school_id for c in ordered):
                continue
            members = [
                self._member(child, position, rule, plan.current.get(child.student_id), school_id)
                for position, child in enumerate(ordered, start=1)
            ]
            in_family.update(c.student_id for c in ordered)
            families.append(
                SiblingFamily(guardians=self._family_guardians(group, guardians), members=members)
            )

        families.sort(
            key=lambda f: (
                not any(m.action in _NEEDS_ACTION for m in f.members),
                f.members[0].student_name.lower(),
            )
        )
        plan.families = families

        orphans = [
            a
            for sid, a in plan.current.items()
            if sid not in in_family and a.concession_id in rule.concession_ids
        ]
        plan.no_longer_eligible = await self._orphans(orphans, school_id)
        return plan

    # =====================================================================
    # Queries
    # =====================================================================

    async def _family_links(
        self, school_id: UUID
    ) -> list[tuple[UUID, UUID, GuardianRelationship, str]]:
        """Every parental link in a family that has a child at this campus.

        A recursive CTE from this campus's children outwards: child -> parent ->
        that parent's other children -> their other parent -> ... until nothing new
        is found. `UNION` (not `UNION ALL`) drops rows already seen, which is what
        makes the recursion stop. Organization-wide on purpose (RLS still bounds it to
        the organization); see "ACROSS CAMPUSES" above.
        """
        eligible = (
            select(
                GuardianStudent.guardian_id.label("guardian_id"),
                GuardianStudent.student_id.label("student_id"),
                GuardianStudent.relationship_type.label("relationship_type"),
                Guardian.full_name.label("guardian_name"),
                Student.school_id.label("school_id"),
            )
            .join(Guardian, Guardian.id == GuardianStudent.guardian_id)
            .join(Student, Student.id == GuardianStudent.student_id)
            .where(
                GuardianStudent.deleted_at.is_(None),
                GuardianStudent.relationship_type.in_(PARENTAL),
                Guardian.deleted_at.is_(None),
                Student.deleted_at.is_(None),
                Student.status == StudentStatus.ACTIVE,
                Student.section_id.is_not(None),
            )
            .cte("eligible")
        )
        family = (
            select(eligible.c.student_id)
            .where(eligible.c.school_id == school_id)
            .cte("family", recursive=True)
        )
        via = eligible.alias("via")
        kin = eligible.alias("kin")
        family = family.union(
            select(kin.c.student_id)
            .select_from(family)
            .join(via, via.c.student_id == family.c.student_id)
            .join(kin, kin.c.guardian_id == via.c.guardian_id)
        )
        stmt = select(
            eligible.c.guardian_id,
            eligible.c.student_id,
            eligible.c.relationship_type,
            eligible.c.guardian_name,
        ).where(eligible.c.student_id.in_(select(family.c.student_id)))
        rows = (await self.session.execute(stmt)).all()
        return [
            (
                row.guardian_id,
                row.student_id,
                GuardianRelationship(row.relationship_type),
                row.guardian_name,
            )
            for row in rows
        ]

    @staticmethod
    def _group(links: Iterable[tuple[UUID, UUID, Any, Any]]) -> list[set[UUID]]:
        """Children joined by shared parents, as sets of student ids (union-find)."""
        parent: dict[UUID, UUID] = {}

        def find(node: UUID) -> UUID:
            parent.setdefault(node, node)
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        first_child: dict[UUID, UUID] = {}
        for guardian_id, student_id, *_ in links:
            find(student_id)
            if guardian_id in first_child:
                parent[find(student_id)] = find(first_child[guardian_id])
            else:
                first_child[guardian_id] = student_id

        groups: dict[UUID, set[UUID]] = {}
        for node in parent:
            groups.setdefault(find(node), set()).add(node)
        return list(groups.values())

    async def _children(self, student_ids: set[UUID]) -> dict[UUID, _Child]:
        if not student_ids:
            return {}
        stmt = (
            select(
                Student.id,
                Student.first_name,
                Student.last_name,
                Student.admission_number,
                Student.school_id,
                Student.enrolled_on,
                Student.created_at,
                School.name.label("campus_name"),
                SchoolClass.name.label("class_name"),
                SchoolClass.level,
                Section.name.label("section_name"),
            )
            .join(School, School.id == Student.school_id)
            .outerjoin(Section, Section.id == Student.section_id)
            .outerjoin(SchoolClass, SchoolClass.id == Section.class_id)
            .where(Student.id.in_(list(student_ids)))
        )
        return {
            row.id: _Child(
                student_id=row.id,
                name=f"{row.first_name} {row.last_name}",
                admission_number=row.admission_number,
                school_id=row.school_id,
                campus_name=row.campus_name,
                class_name=row.class_name,
                class_level=row.level,
                section_name=row.section_name,
                enrolled_on=row.enrolled_on,
                created_at=row.created_at,
            )
            for row in (await self.session.execute(stmt)).all()
        }

    async def _current(
        self, academic_year: str, rule: FeeSiblingRule, campus_ids: set[UUID]
    ) -> dict[UUID, StudentFeeAssignment]:
        """This campus's live arrangements on the rule's head: those of children in a
        family, plus anyone on a sibling scheme (who may no longer have a sibling)."""
        stmt = (
            select(StudentFeeAssignment)
            .join(Student, Student.id == StudentFeeAssignment.student_id)
            .where(
                StudentFeeAssignment.school_id == require_school_id(),
                StudentFeeAssignment.academic_year == academic_year,
                StudentFeeAssignment.head_id == rule.head_id,
                StudentFeeAssignment.deleted_at.is_(None),
                Student.deleted_at.is_(None),
                Student.status == StudentStatus.ACTIVE,
                StudentFeeAssignment.student_id.in_(list(campus_ids))
                | StudentFeeAssignment.concession_id.in_(list(rule.concession_ids)),
            )
            .options(
                selectinload(StudentFeeAssignment.concession),
                selectinload(StudentFeeAssignment.head),
            )
        )
        return {a.student_id: a for a in (await self.session.execute(stmt)).scalars()}

    async def _orphans(
        self, assignments: Sequence[StudentFeeAssignment], school_id: UUID
    ) -> list[SiblingMember]:
        children = await self._children({a.student_id for a in assignments})
        members = [
            SiblingMember(
                **self._identity(children[a.student_id], school_id),
                position=None,
                action=SiblingAction.REMOVE,
                current=self._describe(a),
                reason="No brother or sister enrolled now.",
            )
            for a in assignments
            if a.student_id in children
        ]
        return sorted(members, key=lambda m: m.student_name.lower())

    # =====================================================================
    # Shaping
    # =====================================================================

    def _member(
        self,
        child: _Child,
        position: int,
        rule: FeeSiblingRule,
        current: StudentFeeAssignment | None,
        school_id: UUID,
    ) -> SiblingMember:
        identity = self._identity(child, school_id)
        if child.school_id != school_id:
            return SiblingMember(**identity, position=position, action=SiblingAction.OTHER_CAMPUS)

        described = self._describe(current) if current else None
        ours = current is not None and current.concession_id in rule.concession_ids
        proposed = rule.concession_for(position)

        if proposed is None:
            if ours:
                return SiblingMember(
                    **identity,
                    position=position,
                    action=SiblingAction.REMOVE,
                    current=described,
                    reason="Pays in full as the child in the highest class.",
                )
            return SiblingMember(
                **identity, position=position, action=SiblingAction.FULL_FEE, current=described
            )

        base: dict[str, Any] = {
            **identity,
            "position": position,
            "proposed_concession_id": proposed.id,
            "proposed_concession_name": proposed.name,
            "current": described,
        }
        if current is not None and current.concession_id == proposed.id:
            return SiblingMember(**base, action=SiblingAction.OK)
        if current is not None and not ours:
            return SiblingMember(
                **base,
                action=SiblingAction.CONFLICT,
                reason=(
                    f"Already has {described} on {rule.head.name}. Change it on the "
                    "student's page if the sibling discount should replace it."
                ),
            )
        if not proposed.is_active:
            return SiblingMember(
                **base,
                action=SiblingAction.CONFLICT,
                reason=f"The scheme '{proposed.name}' is inactive.",
            )
        return SiblingMember(**base, action=SiblingAction.CHANGE if ours else SiblingAction.APPLY)

    @staticmethod
    def _identity(child: _Child, school_id: UUID) -> dict[str, Any]:
        return {
            "student_id": child.student_id,
            "student_name": child.name,
            "admission_number": child.admission_number,
            "class_name": child.class_name,
            "class_level": child.class_level,
            "section_name": child.section_name,
            "campus_name": child.campus_name,
            "at_this_campus": child.school_id == school_id,
        }

    @staticmethod
    def _describe(assignment: StudentFeeAssignment) -> str:
        match assignment.mode:
            case StudentFeeAssignmentMode.DISCOUNT if assignment.concession is not None:
                return assignment.concession.name
            case StudentFeeAssignmentMode.DISCOUNT if assignment.percent is not None:
                return f"a {assignment.percent}% discount"
            case StudentFeeAssignmentMode.DISCOUNT:
                return f"a discount of {assignment.amount}"
            case StudentFeeAssignmentMode.OVERRIDE:
                return f"an agreed rate of {assignment.amount}"
            case StudentFeeAssignmentMode.EXCLUDED:
                return "no charge for this head"
            case _:
                return f"an added charge of {assignment.amount}"

    @staticmethod
    def _family_guardians(
        group: set[UUID],
        guardians: dict[UUID, dict[UUID, tuple[str, set[GuardianRelationship]]]],
    ) -> list[SiblingGuardian]:
        merged: dict[UUID, tuple[str, set[GuardianRelationship]]] = {}
        for student_id in group:
            for guardian_id, (name, relationships) in guardians.get(student_id, {}).items():
                entry = merged.setdefault(guardian_id, (name, set()))
                entry[1].update(relationships)
        return sorted(
            (
                SiblingGuardian(
                    guardian_id=guardian_id,
                    full_name=name,
                    relationships=sorted(relationships, key=PARENTAL.index),
                )
                for guardian_id, (name, relationships) in merged.items()
            ),
            key=lambda g: (PARENTAL.index(g.relationships[0]), g.full_name.lower()),
        )

    def _review_read(self, academic_year: str, plan: _Plan) -> SiblingReview:
        members = list(plan.campus_members().values())
        return SiblingReview(
            academic_year=academic_year,
            rule=self._rule_read(plan.rule),
            families=plan.families,
            no_longer_eligible=plan.no_longer_eligible,
            to_apply=sum(m.action in (SiblingAction.APPLY, SiblingAction.CHANGE) for m in members),
            to_remove=sum(m.action is SiblingAction.REMOVE for m in members),
            conflicts=sum(m.action is SiblingAction.CONFLICT for m in members),
        )

    @staticmethod
    def _scheme(concession: FeeConcession | None) -> SiblingSchemeRead | None:
        if concession is None:
            return None
        return SiblingSchemeRead(
            id=concession.id,
            name=concession.name,
            kind=concession.kind,
            value=concession.value,
            is_active=concession.is_active,
        )

    def _rule_read(self, rule: FeeSiblingRule) -> FeeSiblingRuleRead:
        second = self._scheme(rule.second_concession)
        assert second is not None
        return FeeSiblingRuleRead(
            id=rule.id,
            head_id=rule.head_id,
            head_name=rule.head.name,
            second=second,
            third=self._scheme(rule.third_concession),
            later=self._scheme(rule.later_concession),
            updated_at=rule.updated_at,
        )

    @staticmethod
    def _audit_values(rule: FeeSiblingRule) -> dict[str, Any]:
        return {
            "head_id": str(rule.head_id),
            "second_concession_id": str(rule.second_concession_id),
            "third_concession_id": (
                str(rule.third_concession_id) if rule.third_concession_id else None
            ),
            "later_concession_id": (
                str(rule.later_concession_id) if rule.later_concession_id else None
            ),
        }
