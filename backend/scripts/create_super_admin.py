"""Seed a platform Super Admin.

WHY THIS SCRIPT EXISTS
    A super admin onboards and approves schools, so the very first one cannot be
    created through a normal (tenant-scoped, self-service) signup -- and exposing a
    public "make me a super admin" endpoint would be a privilege-escalation hole. It
    is therefore an out-of-band operator action, run once per environment.

    It also demonstrates the correct pattern for code running OUTSIDE an HTTP request:
    `session_scope(super_admin=True)` binds the ambient tenant explicitly, since there
    is no JWT to read it from.

USAGE
    uv run python -m scripts.create_super_admin --email you@example.com --name "You"
    (password is read from the SMS_SUPERADMIN_PASSWORD env var, or prompted).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

import app.db.registry  # noqa: F401  (registers every model so FKs resolve, e.g. users->schools)
from app.core.config import get_settings
from app.core.otp import normalise_identifier
from app.core.security import hash_password
from app.db.session import dispose_engine, init_engine, session_scope
from app.modules.auth.models import User, UserRole, UserStatus
from app.modules.auth.repository import UserRepository


async def _create(email: str, full_name: str, password: str) -> None:
    settings = get_settings()
    if not settings.DB_ENABLED:
        raise SystemExit("DB_ENABLED is false; point .env at PostgreSQL first.")

    init_engine(settings)
    try:
        # super_admin=True so the schools/RLS machinery treats this as a platform
        # actor; users has no RLS, but binding the flag keeps the intent explicit.
        async with session_scope(super_admin=True) as session:
            repo = UserRepository(session)
            if await repo.email_taken(email):
                raise SystemExit(f"A user with email {email} already exists.")
            user = User(
                school_id=None,  # platform staff belong to no school
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=UserRole.SUPER_ADMIN,
                status=UserStatus.ACTIVE,
            )
            session.add(user)
            await session.flush()
            print(f"Created super admin {email} (id={user.id}).")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a platform super admin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = os.environ.get("SMS_SUPERADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        raise SystemExit(1)

    # Validate with the SAME validator the login endpoint uses.
    #
    # WHY: this script writes straight to the table and so bypasses the `EmailStr`
    # check on the API schemas. Without this, an address in a reserved TLD
    # (`.test`, `.local`, `.example`) is accepted here and then rejected with a 422
    # by POST /auth/login -- producing a super admin that exists in the database and
    # can never sign in, with nothing to explain why.
    try:
        validated = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"] if exc.errors() else "invalid address"
        print(f"{args.email!r} is not a usable login email: {reason}", file=sys.stderr)
        raise SystemExit(1) from exc

    asyncio.run(_create(normalise_identifier(validated), args.name.strip(), password))


if __name__ == "__main__":
    main()
