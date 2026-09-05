"""Audit trail writers.

WHY THIS FILE EXISTS
    Spec §4.4: "Every auth mutation writes an `audit_logs` row", and §7.1 requires
    one on every invitation action. Scattering hand-rolled `AuditLog(...)`
    constructions through six services guarantees drift -- different action names for
    the same event, forgotten actor ids, and eventually a mutation nobody recorded.

RESPONSIBILITY
    Provide one call for tenant audit rows and one for platform audit rows, plus the
    canonical action-name constants. No querying -- reading the trail is the audit
    module's job.

INTERACTIONS
    Called by every service that mutates state. Writes into the caller's existing
    session so the audit row commits in the SAME transaction as the change it
    describes.

=============================================================================
THE AUDIT ROW SHARES THE CALLER'S TRANSACTION. THAT IS THE WHOLE DESIGN.
=============================================================================
    It would be tempting to write audit rows on a separate connection, or to queue
    them, so that an audit failure cannot fail a user's request. Both are wrong here.

    Same transaction means the two facts -- "the member was suspended" and "we
    recorded that the member was suspended" -- are atomic. Either both happened or
    neither did. With a separate connection, a crash between them produces a change
    with no record, which is exactly the state an audit trail exists to make
    impossible.

    The cost is real: an audit write that fails rolls back the user's action. That is
    the correct trade for a system holding minors' records, where "we cannot tell you
    who changed this" is a worse outcome than "the change did not go through".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admin.models import PlatformAuditLog
from app.modules.rbac.models import AuditLog


class AuditAction:
    """Canonical action names.

    Constants rather than free strings so that a typo is an AttributeError at import
    time, and so the set of auditable actions is enumerable -- which is what makes
    "alert when X happens" possible without grepping the codebase.

    Naming is `subject.verb_past_tense`, always past tense: an audit row records what
    HAPPENED, never what was attempted.
    """

    # --- Authentication -----------------------------------------------------
    USER_REGISTERED = "user.registered"
    USER_EMAIL_VERIFIED = "user.email_verified"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOCKED_OUT = "user.locked_out"
    USER_LOGGED_OUT = "user.logged_out"
    USER_LOGGED_OUT_ALL = "user.logged_out_all"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    USER_PASSWORD_RESET = "user.password_reset"
    SESSION_CONTEXT_SWITCHED = "session.context_switched"
    SESSION_REUSE_DETECTED = "session.reuse_detected"

    # --- Organization & schools ---------------------------------------------
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_UPDATED = "organization.updated"
    OWNERSHIP_TRANSFERRED = "organization.ownership_transferred"
    SCHOOL_CREATED = "school.created"
    SCHOOL_UPDATED = "school.updated"
    SCHOOL_ARCHIVED = "school.archived"

    # --- Access control -----------------------------------------------------
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    ROLE_PERMISSIONS_CHANGED = "role.permissions_changed"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_CREATED = "member.created"
    MEMBER_SUSPENDED = "member.suspended"
    MEMBER_REACTIVATED = "member.reactivated"
    MEMBER_REMOVED = "member.removed"

    # --- Invitations --------------------------------------------------------
    INVITATION_SENT = "invitation.sent"
    INVITATION_RESENT = "invitation.resent"
    INVITATION_REVOKED = "invitation.revoked"
    INVITATION_ACCEPTED = "invitation.accepted"

    # --- Guardians (parent registry and portal access) ----------------------
    #
    # `GUARDIAN_LINKED` / `GUARDIAN_UNLINKED` record against the STUDENT, not the
    # link row: the question this trail answers is "who was given access to this
    # child, and when", and an audit filtered by a join-table id cannot answer it.
    #
    # The phone change and the two portal toggles are separate actions rather than one
    # `GUARDIAN_UPDATED`, because they are the three that change who can SIGN IN. An
    # investigator asking "who gave this handset access to this family" must be able
    # to filter for exactly those, not read every name correction in the school.
    GUARDIAN_REGISTERED = "guardian.registered"
    GUARDIAN_UPDATED = "guardian.updated"
    GUARDIAN_REMOVED = "guardian.removed"
    GUARDIAN_PHONE_CHANGED = "guardian.phone_changed"
    GUARDIAN_PORTAL_ENABLED = "guardian.portal_enabled"
    GUARDIAN_PORTAL_DISABLED = "guardian.portal_disabled"
    GUARDIAN_LINKED = "guardian.linked"
    GUARDIAN_UNLINKED = "guardian.unlinked"
    GUARDIAN_LINK_UPDATED = "guardian.link_updated"

    # --- Billing ------------------------------------------------------------
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    SUBSCRIPTION_TRIAL_EXPIRED = "subscription.trial_expired"
    SUBSCRIPTION_SUSPENDED = "subscription.suspended"
    SUBSCRIPTION_PERIOD_CANCELLED = "subscription.period_cancelled"
    ORGANIZATION_ANONYMIZED = "organization.anonymized"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_FAILED = "payment.failed"
    PLAN_LIMIT_EXCEEDED = "entitlement.limit_exceeded"

    # --- Fees (what a school bills its students) ----------------------------
    #
    # Distinct from the billing actions above, which record what the school owes
    # EduCloud. Two money flows between different parties; sharing an action name
    # would make "show me every payment" answer the wrong question.
    FEE_HEAD_CREATED = "fee_head.created"
    FEE_HEAD_UPDATED = "fee_head.updated"
    FEE_HEAD_DELETED = "fee_head.deleted"
    FEE_STRUCTURE_CREATED = "fee_structure.created"
    FEE_STRUCTURE_UPDATED = "fee_structure.updated"
    FEE_STRUCTURE_ITEM_CHANGED = "fee_structure.item_changed"
    FEE_STRUCTURE_ACTIVATED = "fee_structure.activated"
    FEE_STRUCTURE_ARCHIVED = "fee_structure.archived"
    FEE_VOUCHER_GENERATED = "fee_voucher.generated"
    FEE_VOUCHER_ISSUED = "fee_voucher.issued"
    FEE_VOUCHER_VOIDED = "fee_voucher.voided"
    FEE_PAYMENT_RECORDED = "fee_payment.recorded"
    FEE_PAYMENT_REVERSED = "fee_payment.reversed"

    # --- Stationery (what a school SELLS its students) ----------------------
    #
    # Its own action names rather than reuse of the fee-head ones, even though the
    # catalogs are structurally alike. "Who changed the price of a copy last term?"
    # is a question a store keeper asks and a tuition rename would drown out.
    STATIONERY_ITEM_CREATED = "stationery_item.created"
    STATIONERY_ITEM_UPDATED = "stationery_item.updated"
    STATIONERY_ITEM_DELETED = "stationery_item.deleted"
    # A charge added to or removed from ONE student's draft challan, as opposed to
    # the whole-class structure change `FEE_STRUCTURE_ITEM_CHANGED` records.
    FEE_VOUCHER_CHARGE_ADDED = "fee_voucher.charge_added"
    FEE_VOUCHER_CHARGE_REMOVED = "fee_voucher.charge_removed"

    # --- Academic calendar and curriculum -----------------------------------
    #
    # The calendar is low-frequency and high-consequence: moving the boundary of a
    # year silently restates every attendance percentage and every report card
    # quoted against it. `before`/`after` on these rows is what lets someone answer
    # "why did last term's figures change?" months later.
    ACADEMIC_YEAR_CREATED = "academic_year.created"
    ACADEMIC_YEAR_UPDATED = "academic_year.updated"
    ACADEMIC_YEAR_DELETED = "academic_year.deleted"
    ACADEMIC_YEAR_ACTIVATED = "academic_year.activated"
    TERM_CREATED = "term.created"
    TERM_UPDATED = "term.updated"
    TERM_DELETED = "term.deleted"
    SUBJECT_CREATED = "subject.created"
    SUBJECT_UPDATED = "subject.updated"
    SUBJECT_DELETED = "subject.deleted"
    CLASS_SUBJECT_ADDED = "class_subject.added"
    CLASS_SUBJECT_UPDATED = "class_subject.updated"
    CLASS_SUBJECT_REMOVED = "class_subject.removed"

    # --- Exams ---------------------------------------------------------------
    #
    # Marks entry is ONE event per sheet save, not one per student: the auditable
    # act is "this teacher submitted Grade 5 maths marks", and five hundred rows
    # per save would bury the trail the day results are disputed.
    EXAM_CREATED = "exam.created"
    EXAM_UPDATED = "exam.updated"
    EXAM_DELETED = "exam.deleted"
    EXAM_PAPER_ADDED = "exam_paper.added"
    EXAM_PAPER_UPDATED = "exam_paper.updated"
    EXAM_PAPER_REMOVED = "exam_paper.removed"
    EXAM_MARKS_ENTERED = "exam.marks_entered"

    # --- Enrollment history --------------------------------------------------
    #
    # `entity_type` is `student` throughout, deliberately: the question this trail
    # answers is "what happened to THIS CHILD's placement", and a trail filtered by
    # an enrollment-row id cannot answer it.
    STUDENT_ENROLLED = "student.enrolled"
    STUDENT_TRANSFERRED = "student.transferred"
    STUDENT_ENROLLMENT_CLOSED = "student.enrollment_closed"
    STUDENT_PROMOTED = "student.promoted"
    STUDENT_ADMISSION_ACCEPTED = "student.admission_accepted"
    STUDENT_ADMISSION_REJECTED = "student.admission_rejected"

    # --- Attendance ----------------------------------------------------------
    #
    # SUBMITTED and AMENDED are separate actions, not one "changed", because they
    # answer different questions and are held by different permissions. "Who marked
    # today's register?" is routine; "who rewrote a register that was already
    # submitted?" is the one an investigation starts from, and it must not be
    # buried among thousands of the former.
    ATTENDANCE_SESSION_OPENED = "attendance_session.opened"
    ATTENDANCE_SESSION_SUBMITTED = "attendance_session.submitted"
    ATTENDANCE_SESSION_REOPENED = "attendance_session.reopened"
    ATTENDANCE_SESSION_DISCARDED = "attendance_session.discarded"
    ATTENDANCE_AMENDED = "attendance_record.amended"

    # --- Per-student fee arrangements ---------------------------------------
    #
    # `entity_type` is `student` rather than `student_fee_assignment`, deliberately:
    # the question this trail answers is "what changed about what THIS CHILD pays",
    # and an audit filtered by a join-table id cannot answer it.
    STUDENT_FEE_ASSIGNED = "student_fee.assigned"
    STUDENT_FEE_UNASSIGNED = "student_fee.unassigned"

    # Concessions, fines and the running ledger. `FEE_LATE_FEE_APPLIED` is the only
    # action in this enum a JOB writes with no human actor -- `actor_user_id` is null
    # on it, which is honest: "who fined us?" is answered by "the policy did".
    FEE_CONCESSION_CREATED = "fee_concession.created"
    FEE_CONCESSION_UPDATED = "fee_concession.updated"
    FEE_CONCESSION_DELETED = "fee_concession.deleted"
    # Unattended generation. The RUN is audited as well as the schedule, because
    # "who billed the whole campus in August?" has the answer "nobody -- the schedule
    # did", and that answer has to be visible rather than inferred from an empty
    # actor column on four hundred vouchers.
    FEE_BILLING_SCHEDULE_SET = "fee_billing_schedule.set"
    FEE_BILLING_RUN_COMPLETED = "fee_billing_run.completed"
    FEE_LATE_FEE_POLICY_SET = "fee_late_fee_policy.set"
    FEE_LATE_FEE_POLICY_DELETED = "fee_late_fee_policy.deleted"
    FEE_LATE_FEE_APPLIED = "fee_late_fee.applied"
    # A manual balance movement with no voucher and no receipt behind it -- the one
    # fee action that can make money disappear, which is why it is `fee:void`.
    FEE_LEDGER_ADJUSTED = "fee_ledger.adjusted"


class PlatformAuditAction:
    """Action names for platform-operator activity."""

    ADMIN_LOGGED_IN = "platform_admin.logged_in"
    ADMIN_LOGIN_FAILED = "platform_admin.login_failed"
    ADMIN_LOGGED_OUT = "platform_admin.logged_out"
    ADMIN_REFRESH_REUSE_DETECTED = "platform_admin.refresh_reuse_detected"
    ORGANIZATION_SUSPENDED = "platform.organization_suspended"
    ORGANIZATION_REACTIVATED = "platform.organization_reactivated"
    ORGANIZATION_PLAN_OVERRIDDEN = "platform.organization_plan_overridden"
    IMPERSONATION_STARTED = "platform.impersonation_started"
    PLAN_CREATED = "platform.plan_created"
    PLAN_UPDATED = "platform.plan_updated"
    PLAN_DELETED = "platform.plan_deleted"


async def record_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    action: str,
    school_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_membership_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append a tenant audit row inside the caller's transaction.

    `actor_user_id` is nullable because some auditable events have no human actor --
    a failed login for an address that matches no account, or a subscription expiring
    on a schedule. Recording those with a null actor is more honest than attributing
    them to a system user that does not exist.

    No `flush()`: the row goes out with the rest of the unit of work. Flushing here
    would force a round-trip in the middle of every mutation for an id nobody reads.
    """
    entry = AuditLog(
        organization_id=organization_id,
        school_id=school_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        ip=ip,
        user_agent=user_agent,
    )
    session.add(entry)
    return entry


async def record_platform_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_admin_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    target_organization_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> PlatformAuditLog:
    """Append a platform audit row.

    Goes to a different table from `record_audit` because these actions cross
    organizations. See `PlatformAuditLog`'s docstring for why containment matters:
    a suspended organization must not be able to influence the visibility of the
    record describing its own suspension.
    """
    entry = PlatformAuditLog(
        actor_admin_id=actor_admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        target_organization_id=target_organization_id,
        audit_metadata=metadata or {},
        ip=ip,
        user_agent=user_agent,
    )
    session.add(entry)
    return entry
