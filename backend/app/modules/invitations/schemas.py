"""Invitation request/response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, model_validator

from app.common.schemas import BaseSchema


class InvitationCreate(BaseSchema):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)
    role_id: UUID


class InvitationRead(BaseSchema):
    """A pending or historical invitation, for the principal's invitations screen.

    Carries no token and no digest. The digest is a credential-equivalent: anyone
    holding it can confirm a guessed token offline, so it never leaves the database.
    """

    id: UUID
    email: str
    full_name: str | None
    school_id: UUID | None
    role_id: UUID
    role_name: str | None
    status: str
    expires_at: datetime
    resent_count: int
    last_sent_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime


class InvitationPreview(BaseSchema):
    """What an UNAUTHENTICATED token holder is allowed to see (spec §7.2).

    Deliberately minimal. Whoever holds this token has proven only that they received
    an email -- possibly by interception or forwarding. Everything here is already in
    the invitation email they were sent; nothing else is added.

    `requires_signup` tells the frontend which form to render: full signup for a new
    person, or a sign-in prompt for someone who already has an account.
    """

    school_name: str | None
    role_name: str | None
    email: str
    inviter_name: str | None
    requires_signup: bool
    expires_at: datetime


class InvitationAccept(BaseSchema):
    """Accept an invitation. Two shapes, one endpoint (spec §7.2).

    NEW USER      -> `{ token, full_name, password }`
    EXISTING USER -> `{ token }`, with an authenticated session for the same address

    The validator below rejects the halfway case -- a name without a password -- at
    the schema boundary, so the service never has to reason about a partially
    specified signup.
    """

    token: str = Field(min_length=16, max_length=512)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _name_and_password_travel_together(self) -> InvitationAccept:
        if bool(self.full_name) != bool(self.password):
            raise ValueError(
                "Provide both full_name and password to create an account, or neither "
                "to accept with an existing signed-in account."
            )
        return self


class InvitationAcceptResponse(BaseSchema):
    """Result of acceptance, with enough context to route the user onward."""

    user_id: UUID
    membership_id: UUID
    organization_id: UUID
    school_id: UUID | None
    role_code: str
    created_account: bool
    message: str
