"""Auth HTTP endpoints.

WHY THIS FILE EXISTS
    Maps HTTP to `AuthService`. Handlers are thin: parse, delegate, return. The one
    piece of real wiring here is the email dispatcher -- it is the seam where the
    transport-agnostic service meets FastAPI's `BackgroundTasks`, so a slow SMTP
    handshake never blocks the response (see the rationale in common/email/sender.py).

INTERACTIONS
    Mounted at `/api/v1/auth`. Most routes are PUBLIC (they run before a session
    exists); `/me` requires a bearer token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from app.api.deps import CurrentUser, DbSession, PublicDbSession, SettingsDep
from app.common.email.sender import EmailMessage, EmailSender, build_email_sender
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResult,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenPair,
    UserRead,
    Verify2FARequest,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService, EmailDispatcher

router = APIRouter()


# ---------------------------------------------------------------------------
# Email dispatch: bridge the service's EmailDispatcher Protocol to BackgroundTasks
# ---------------------------------------------------------------------------


class _BackgroundEmailDispatcher:
    """Queues each message on FastAPI's BackgroundTasks so delivery happens after
    the response is returned. Satisfies the service's `EmailDispatcher` Protocol."""

    def __init__(self, tasks: BackgroundTasks, sender: EmailSender) -> None:
        self._tasks = tasks
        self._sender = sender

    def dispatch(self, message: EmailMessage) -> None:
        self._tasks.add_task(self._sender.send, message)


def get_email_dispatcher(
    background_tasks: BackgroundTasks, settings: SettingsDep
) -> EmailDispatcher:
    return _BackgroundEmailDispatcher(background_tasks, build_email_sender(settings))


DispatcherDep = Annotated[EmailDispatcher, Depends(get_email_dispatcher)]


@dataclass(frozen=True, slots=True)
class ClientMeta:
    """The caller's user-agent and IP, captured for the refresh-token session record."""

    user_agent: str | None
    ip: str | None


def get_client_meta(request: Request) -> ClientMeta:
    return ClientMeta(
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


ClientMetaDep = Annotated[ClientMeta, Depends(get_client_meta)]


# ---------------------------------------------------------------------------
# Registration & verification
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a school and its first admin",
)
async def register(
    payload: RegisterRequest, db: PublicDbSession, dispatcher: DispatcherDep, settings: SettingsDep
) -> RegisterResponse:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).register(payload)


@router.post("/verify-email", response_model=MessageResponse, summary="Verify an email address")
async def verify_email(
    payload: VerifyEmailRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
) -> MessageResponse:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).verify_email(payload)


@router.post(
    "/resend-verification", response_model=MessageResponse, summary="Resend a verification code"
)
async def resend_verification(
    payload: ResendVerificationRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
) -> MessageResponse:
    service = AuthService(db, dispatcher=dispatcher, settings=settings)
    return await service.resend_verification(payload.email)


# ---------------------------------------------------------------------------
# Login, 2FA, tokens
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResult, summary="Sign in")
async def login(
    payload: LoginRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
    meta: ClientMetaDep,
) -> LoginResult:
    service = AuthService(db, dispatcher=dispatcher, settings=settings)
    return await service.login(payload, user_agent=meta.user_agent, ip=meta.ip)


@router.post("/login/verify-2fa", response_model=TokenPair, summary="Complete 2FA sign-in")
async def verify_2fa(
    payload: Verify2FARequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
    meta: ClientMetaDep,
) -> TokenPair:
    service = AuthService(db, dispatcher=dispatcher, settings=settings)
    return await service.verify_2fa(payload, user_agent=meta.user_agent, ip=meta.ip)


@router.post("/refresh", response_model=TokenPair, summary="Rotate the token pair")
async def refresh(
    payload: RefreshRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
    meta: ClientMetaDep,
) -> TokenPair:
    service = AuthService(db, dispatcher=dispatcher, settings=settings)
    return await service.refresh(payload.refresh_token, user_agent=meta.user_agent, ip=meta.ip)


@router.post("/logout", response_model=MessageResponse, summary="Revoke a refresh token")
async def logout(
    payload: LogoutRequest, db: PublicDbSession, dispatcher: DispatcherDep, settings: SettingsDep
) -> MessageResponse:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).logout(
        payload.refresh_token
    )


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@router.post("/forgot-password", response_model=MessageResponse, summary="Request a reset code")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
) -> MessageResponse:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).forgot_password(payload)


@router.post("/reset-password", response_model=MessageResponse, summary="Reset a password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: PublicDbSession,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
) -> MessageResponse:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).reset_password(payload)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserRead, summary="Current user profile")
async def me(
    user: CurrentUser, db: DbSession, dispatcher: DispatcherDep, settings: SettingsDep
) -> UserRead:
    return await AuthService(db, dispatcher=dispatcher, settings=settings).get_profile(user.user_id)
