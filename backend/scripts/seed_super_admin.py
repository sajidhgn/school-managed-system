"""Seed -- or repair -- the platform super admin so `/platform/login` works.

WHY THIS SCRIPT EXISTS
    `python -m app.cli seed` creates the super admin, but only when one is ABSENT:
    `create_platform_admin()` returns the existing row untouched. That is the right
    behaviour for a seeder that also upserts permissions and plans, because a re-run
    must never silently rewrite a live operator's credentials.

    It leaves a real gap, though. Every one of these locks an operator out, and none
    of them is fixed by re-running `seed`:

      * the password in `.env` was changed after the account was minted
      * five bad guesses set `locked_until` (spec §4.4 lockout)
      * `is_active` was flipped to false
      * the account was seeded with an address nobody remembers

    There is deliberately no emailed reset for this role (see
    `platform_admin/models.py`: an emailed reset means the platform's security
    reduces to the security of one inbox), so the recovery path has to be
    out-of-band. This is that path.

WHAT IT DOES
    Converges the super admin onto the credentials in `.env`, which is what "seed"
    means for a declarative resource: create it if absent, and if present reset every
    gate the login checks -- password, `is_active`, `locked_until`,
    `failed_login_count`. See `PlatformService.authenticate` for that gate list; this
    script exists to satisfy all of it at once.

    MFA IS NOT TOUCHED BY DEFAULT. Clearing an enrolled secret is a security
    downgrade, and in production it converts a working account into one that cannot
    sign in at all (`authenticate` refuses an unenrolled admin there). `--reset-mfa`
    is opt-in and says so.

USAGE
    uv run python scripts/seed_super_admin.py                  # from .env
    uv run python scripts/seed_super_admin.py --email you@example.com
    uv run python scripts/seed_super_admin.py --password '...' --reset-mfa
    make seed-superadmin
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import secrets
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import app.db.registry  # noqa: F401  (side effect: registers every mapper so FKs resolve)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.session import dispose_engine, init_engine, session_scope
from app.modules.platform_admin.models import PlatformAdmin
from app.modules.platform_admin.service import create_platform_admin

# Mirrors the rejects in `app.cli.seed_superadmin`. Kept in sync deliberately: a
# password this script accepts must be one the seeder would also accept, or the two
# entry points disagree about what a safe credential is.
WEAK_PASSWORDS = frozenset({"changeme", "password", "admin", "superadmin"})
MIN_PRODUCTION_PASSWORD_LENGTH = 16


def _resolve_email(settings: Settings, override: str | None) -> str:
    """Pick the address and prove the login endpoint will accept it.

    `PlatformLoginRequest.email` is an `EmailStr`, so an address accepted by a script
    writing straight to the table can be one that `POST /platform/auth/login` rejects
    with a 422. Reserved TLDs (`.test`, `.local`, `.invalid`) are the common case, and
    they are exactly what someone reaches for when filling in a local `.env`.

    Without this check the failure is miserable to diagnose: the seed reports success,
    the row is in the database, and every sign-in returns a validation error that says
    nothing about the account.
    """
    email = (override or settings.SUPERADMIN_EMAIL).strip()
    if not email:
        raise SystemExit("No email to seed: pass --email, or set SUPERADMIN_EMAIL in backend/.env.")
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise SystemExit(
            f"REFUSING TO SEED: '{email}' is not a valid login address ({exc}). "
            "The platform login endpoint validates it, so this account would be "
            "created but unable to sign in. Reserved TLDs such as .test and .invalid "
            "are rejected -- use a real domain, e.g. admin@example.com."
        ) from exc
    return email


def _resolve_password(settings: Settings, override: str | None) -> tuple[str, bool]:
    """Pick the password, refusing a weak one in production.

    Returns `(password, was_generated)` so the caller knows whether it has to print
    the value -- a generated password that is not shown is an account nobody owns.
    """
    password = override or settings.SUPERADMIN_PASSWORD
    generated = False

    if not password:
        if settings.is_production:
            raise SystemExit(
                "REFUSING TO SEED: SUPERADMIN_PASSWORD is empty in production. "
                "Generating one here would print a platform-wide credential into "
                "deploy logs. Set it explicitly."
            )
        # Outside production, generate rather than fall back to a known default --
        # a default is what everyone leaves in place.
        password = secrets.token_urlsafe(24)
        generated = True

    if settings.is_production and (
        len(password) < MIN_PRODUCTION_PASSWORD_LENGTH or password.lower() in WEAK_PASSWORDS
    ):
        raise SystemExit(
            f"REFUSING TO SEED: the super-admin password must be at least "
            f"{MIN_PRODUCTION_PASSWORD_LENGTH} characters and not a common default "
            "in production. This account can read every tenant's data."
        )

    return password, generated


async def _seed(
    *,
    email: str,
    password: str,
    full_name: str,
    reset_mfa: bool,
    force: bool,
) -> dict[str, object]:
    settings = get_settings()
    if not settings.DB_ENABLED:
        raise SystemExit("DB_ENABLED is false; point backend/.env at PostgreSQL first.")

    init_engine(settings)
    try:
        # `platform_admin=True` with no organization: this row belongs to no tenant,
        # and the seeder has no ambient context to inherit one from. Same binding the
        # CLI seeder uses.
        async with session_scope(None, platform_admin=True) as session:
            admin = (
                await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
            ).scalar_one_or_none()

            if admin is None:
                admin = await create_platform_admin(
                    session, email=email, password=password, full_name=full_name
                )
                return {
                    "action": "created",
                    "id": str(admin.id),
                    "email": admin.email,
                    "mfa": "not enrolled",
                }

            # --- Repair path ------------------------------------------------
            #
            # Overwriting a live operator's password in production is destructive and
            # not something a stray `make` invocation should be able to do, so it is
            # gated. Everywhere else, converging on `.env` is the whole point.
            if settings.is_production and not force:
                raise SystemExit(
                    f"A platform admin already exists for '{email}'. Rewriting its "
                    "password in production is destructive; re-run with --force if "
                    "that is genuinely what you want."
                )

            repaired = []
            admin.password_hash = hash_password(password)
            repaired.append("password")
            if not admin.is_active:
                admin.is_active = True
                repaired.append("is_active")
            if admin.locked_until is not None:
                admin.locked_until = None
                repaired.append("locked_until")
            if admin.failed_login_count:
                admin.failed_login_count = 0
                repaired.append("failed_login_count")
            if reset_mfa and admin.mfa_secret is not None:
                admin.mfa_secret = None
                admin.mfa_last_used_step = None
                repaired.append("mfa_secret")

            await session.flush()
            return {
                "action": "repaired",
                "id": str(admin.id),
                "email": admin.email,
                "fields": ", ".join(repaired),
                "mfa": "enrolled" if admin.mfa_secret else "not enrolled",
            }
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uv run python scripts/seed_super_admin.py",
        description="Create or repair the platform super admin (no signup route exists).",
    )
    parser.add_argument("--email", help="Defaults to SUPERADMIN_EMAIL from .env.")
    parser.add_argument("--password", help="Defaults to SUPERADMIN_PASSWORD from .env.")
    parser.add_argument("--name", default="Platform Super Admin")
    parser.add_argument(
        "--reset-mfa",
        action="store_true",
        help="Clear the enrolled TOTP secret. In production this BLOCKS login until "
        "`python -m app.cli mfa-enroll` is run again.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow rewriting an existing admin's password in production.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings)

    email = _resolve_email(settings, args.email)
    password, generated = _resolve_password(settings, args.password)

    result = asyncio.run(
        _seed(
            email=email,
            password=password,
            full_name=args.name.strip(),
            reset_mfa=args.reset_mfa,
            force=args.force,
        )
    )

    print(f"\nSuper admin {result['action']}.")
    print(f"  id     : {result['id']}")
    print(f"  email  : {result['email']}")
    if "fields" in result:
        print(f"  reset  : {result['fields']}")
    print(f"  MFA    : {result['mfa']}")
    if generated:
        # Printed exactly once -- it is not stored anywhere in readable form.
        print(f"  password (generated, store it now): {password}")

    print(f"\nSign in at /platform/login  (POST {settings.API_V1_PREFIX}/platform/auth/login)")
    if settings.is_production and result["mfa"] == "not enrolled":
        print(
            "\nWARNING: production refuses a login from an admin with no MFA. "
            f"Run: python -m app.cli mfa-enroll --email {result['email']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
