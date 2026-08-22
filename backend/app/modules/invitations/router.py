"""Invitation routes (spec §7, §8 "Members & invitations").

WHY TWO ROUTERS
    `school_router` is permission-gated: sending, listing, resending and revoking are
    all things a principal does inside a school they administer.

    `public_router` is deliberately unauthenticated: verify and accept are reached by
    someone who, by definition, is not yet a member -- and in the new-user case does
    not yet have an account at all. Keeping them in separate routers means a new
    endpoint cannot land in the unauthenticated group by accident.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.cookies import set_auth_cookies
from app.api.deps import (
    AuthContext,
    ClientIp,
    DbSession,
    PublicDbSession,
    SettingsDep,
    get_access_claims,
    require,
)
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import enforce_rate_limit
from app.modules.auth.router import EmailDispatcher, _attach_body_tokens, _wants_body_tokens
from app.modules.auth.service import AuthService
from app.modules.invitations.models import Invitation
from app.modules.invitations.schemas import (
    InvitationAccept,
    InvitationAcceptResponse,
    InvitationCreate,
    InvitationPreview,
    InvitationRead,
)
from app.modules.invitations.service import InvitationService
from app.modules.rbac.router import _assert_school_scope

school_router = APIRouter()
public_router = APIRouter()


def _read(invitation: Invitation) -> InvitationRead:
    """Assemble the response, flattening the role's name onto the row.

    Explicit rather than `model_validate`, because `role_name` crosses a relationship
    and the response must never carry `token_hash` -- which a blanket ORM validation
    against a wider schema could one day start including.
    """
    return InvitationRead(
        id=invitation.id,
        email=invitation.email,
        full_name=invitation.full_name,
        school_id=invitation.school_id,
        role_id=invitation.role_id,
        role_name=invitation.role.name if invitation.role else None,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        resent_count=invitation.resent_count,
        last_sent_at=invitation.last_sent_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
    )


# ---------------------------------------------------------------------------
# School-scoped (permission gated)
# ---------------------------------------------------------------------------


@school_router.post(
    "/{school_id}/invitations",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_invitation(
    school_id: UUID,
    payload: InvitationCreate,
    session: DbSession,
    settings: SettingsDep,
    sender: EmailDispatcher,
    ip: ClientIp,
    request: Request,
    ctx: Annotated[AuthContext, Depends(require("member:invite"))],
) -> InvitationRead:
    """Invite someone to a school (spec §7.1).

    The escalation guard applies here as much as to role editing: the inviter must
    already hold every permission the invited role grants. Without that, inviting is
    simply a slower way to create authority you do not have.
    """
    await enforce_rate_limit(
        "invitation_send",
        f"{ctx.user_id}:{ip or 'unknown'}",
        limit=settings.PUBLIC_MUTATION_RATE_LIMIT,
        window_seconds=settings.PUBLIC_MUTATION_RATE_WINDOW_SECONDS,
    )
    _assert_school_scope(ctx, school_id)
    invitation, _raw = await InvitationService(session, settings, sender).create(
        ctx=ctx,
        school_id=school_id,
        email=payload.email,
        full_name=payload.full_name,
        role_id=payload.role_id,
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )
    await session.refresh(invitation, ["role"])
    return _read(invitation)


@school_router.get("/{school_id}/invitations", response_model=list[InvitationRead])
async def list_invitations(
    school_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    ctx: Annotated[AuthContext, Depends(require("invitation:read"))],
) -> list[InvitationRead]:
    _assert_school_scope(ctx, school_id)
    invitations = await InvitationService(session, settings).list_for_school(school_id)
    return [_read(i) for i in invitations]


@school_router.post(
    "/{school_id}/invitations/{invitation_id}/resend", response_model=InvitationRead
)
async def resend_invitation(
    school_id: UUID,
    invitation_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    sender: EmailDispatcher,
    ip: ClientIp,
    ctx: Annotated[AuthContext, Depends(require("invitation:resend"))],
) -> InvitationRead:
    """Resend with a FRESH token. The previous link dies immediately.

    It cannot re-send the original: only the digest was stored, so the raw token is
    unrecoverable by design. Rotating is also the safer behaviour -- if the first
    email went to a mistyped or compromised address, this kills that link.
    """
    await enforce_rate_limit(
        "invitation_resend",
        f"{ctx.user_id}:{ip or 'unknown'}",
        limit=settings.PUBLIC_MUTATION_RATE_LIMIT,
        window_seconds=settings.PUBLIC_MUTATION_RATE_WINDOW_SECONDS,
    )
    _assert_school_scope(ctx, school_id)
    invitation, _raw = await InvitationService(session, settings, sender).resend(
        ctx=ctx, invitation_id=invitation_id
    )
    await session.refresh(invitation, ["role"])
    return _read(invitation)


@school_router.delete("/{school_id}/invitations/{invitation_id}", response_model=InvitationRead)
async def revoke_invitation(
    school_id: UUID,
    invitation_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    ctx: Annotated[AuthContext, Depends(require("invitation:revoke"))],
) -> InvitationRead:
    """Revoke a pending invitation. The token dies immediately; the seat is returned."""
    _assert_school_scope(ctx, school_id)
    invitation = await InvitationService(session, settings).revoke(
        ctx=ctx, invitation_id=invitation_id
    )
    await session.refresh(invitation, ["role"])
    return _read(invitation)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


@public_router.get("/verify", response_model=InvitationPreview)
async def verify_invitation(
    session: PublicDbSession,
    settings: SettingsDep,
    token: Annotated[str, Query(min_length=16, max_length=512)],
) -> InvitationPreview:
    """Preview an invitation before accepting (spec §7.2). No authentication.

    Returns only what the recipient's own email already told them. See the service's
    docstring for what is deliberately withheld.
    """
    preview = await InvitationService(session, settings).verify(token)
    return InvitationPreview.model_validate(preview)


@public_router.post("/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    payload: InvitationAccept,
    request: Request,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    x_token_transport: Annotated[str | None, Header()] = None,
) -> InvitationAcceptResponse:
    """Accept an invitation, creating an account if needed (spec §7.2).

    =====================================================================
    AUTHENTICATION IS OPTIONAL HERE, AND THAT IS THE DESIGN
    =====================================================================
        An invited person may arrive already signed in (they work at another school
        on the platform) or with no account at all. The endpoint must serve both, so
        it cannot sit behind the auth dependency.

        Instead it attempts to resolve a token and tolerates failure. If a session
        IS present, the service enforces that its email matches the invited address
        exactly -- which is the guard that stops someone accepting an invitation
        forwarded to them.
    """
    authenticated_user_id = None
    try:
        claims = await get_access_claims(request, settings)
        authenticated_user_id = claims.user_id
    except AuthenticationError:
        # No session, or an expired one. Legitimate: this is the new-user path.
        authenticated_user_id = None

    service = InvitationService(session, settings)
    user, membership = await service.accept(
        raw_token=payload.token,
        full_name=payload.full_name,
        password=payload.password,
        authenticated_user_id=authenticated_user_id,
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )

    # Sign them straight in, scoped to the membership they just accepted. Making a
    # brand-new user log in again immediately after choosing a password is friction
    # with no security benefit -- they proved inbox control and set the credential in
    # the same request.
    auth = AuthService(session, settings)
    tokens = await auth.issue_session(
        user=user,
        membership=membership,
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )
    if _wants_body_tokens(x_token_transport):
        # For non-browser clients -- notably the Next.js BFF, which is a confidential
        # client holding the session on the user's behalf. The cookies set above are
        # scoped to this API's origin and are useless to a caller whose browser talks
        # to a different host, so the pair is also offered as headers on request.
        _attach_body_tokens(response, tokens, settings)

    await session.refresh(membership, ["role"])
    return InvitationAcceptResponse(
        user_id=user.id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        school_id=membership.school_id,
        role_code=membership.role.code,
        created_account=payload.password is not None,
        message="Invitation accepted.",
    )
