"""Tests for the OTP primitives.

These assert the SECURITY PROPERTIES of the module, not just that the functions
return values. Each test corresponds to a specific attack the design defends
against -- if one of these regresses, an exploit becomes possible.
"""

from __future__ import annotations

import pytest

from app.core.config import Environment, Settings
from app.core.otp import (
    OTP_LENGTH,
    OtpPurpose,
    generate_otp,
    hash_otp,
    normalise_identifier,
    verify_otp,
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        SECRET_KEY="unit-test-pepper-value",
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_generated_code_has_exact_length() -> None:
    """Zero-padding: without it ~10% of codes are short, shrinking the keyspace."""
    for _ in range(500):
        assert len(generate_otp()) == OTP_LENGTH


def test_generated_code_is_all_digits() -> None:
    for _ in range(200):
        assert generate_otp().isdigit()


def test_codes_are_not_repeated_trivially() -> None:
    """A weak or unseeded RNG shows up immediately as heavy collision.

    500 draws from 10^6 should collide rarely (birthday bound: ~12% chance of any
    collision). Demanding >450 distinct values catches a broken generator without
    being flaky.
    """
    codes = {generate_otp() for _ in range(500)}
    assert len(codes) > 450


# ---------------------------------------------------------------------------
# Hashing and verification
# ---------------------------------------------------------------------------


def test_correct_code_verifies(settings: Settings) -> None:
    code = generate_otp()
    digest = hash_otp(code, purpose=OtpPurpose.LOGIN_2FA, identifier="a@b.com", settings=settings)

    assert verify_otp(
        code, digest, purpose=OtpPurpose.LOGIN_2FA, identifier="a@b.com", settings=settings
    )


def test_wrong_code_fails(settings: Settings) -> None:
    digest = hash_otp(
        "123456", purpose=OtpPurpose.LOGIN_2FA, identifier="a@b.com", settings=settings
    )

    assert not verify_otp(
        "123457", digest, purpose=OtpPurpose.LOGIN_2FA, identifier="a@b.com", settings=settings
    )


def test_plaintext_code_never_appears_in_digest(settings: Settings) -> None:
    """A digest that embeds the code is not a digest."""
    code = "482913"
    digest = hash_otp(
        code, purpose=OtpPurpose.SIGNUP_VERIFY, identifier="a@b.com", settings=settings
    )

    assert code not in digest


# ---------------------------------------------------------------------------
# Domain separation -- the attacks the `purpose` binding prevents
# ---------------------------------------------------------------------------


def test_code_issued_for_one_purpose_cannot_be_used_for_another(settings: Settings) -> None:
    """ATTACK: trigger the benign "verify your email" flow to obtain a code, then
    replay that code against password reset to take over the account.

    Binding the purpose into the digest makes the stolen code cryptographically
    invalid outside its own flow.
    """
    code = generate_otp()
    signup_digest = hash_otp(
        code, purpose=OtpPurpose.SIGNUP_VERIFY, identifier="victim@school.com", settings=settings
    )

    assert not verify_otp(
        code,
        signup_digest,
        purpose=OtpPurpose.PASSWORD_RESET,
        identifier="victim@school.com",
        settings=settings,
    )


def test_code_issued_to_one_identity_cannot_be_used_for_another(settings: Settings) -> None:
    """ATTACK: request a code for your own address, then submit it against the
    victim's account. Binding the identifier defeats this."""
    code = generate_otp()
    attacker_digest = hash_otp(
        code, purpose=OtpPurpose.PASSWORD_RESET, identifier="attacker@evil.com", settings=settings
    )

    assert not verify_otp(
        code,
        attacker_digest,
        purpose=OtpPurpose.PASSWORD_RESET,
        identifier="victim@school.com",
        settings=settings,
    )


def test_digest_is_not_forgeable_without_the_secret(settings: Settings) -> None:
    """ATTACK: attacker dumps the database and tries to brute-force 10^6 codes.

    Without SECRET_KEY they cannot compute a matching digest, so the entire
    keyspace is useless to them. Demonstrated here by a wrong pepper failing.
    """
    code = generate_otp()
    digest = hash_otp(code, purpose=OtpPurpose.LOGIN_2FA, identifier="a@b.com", settings=settings)

    attacker_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        SECRET_KEY="attacker-does-not-have-the-real-pepper",
    )
    assert not verify_otp(
        code,
        digest,
        purpose=OtpPurpose.LOGIN_2FA,
        identifier="a@b.com",
        settings=attacker_settings,
    )


def test_separator_prevents_field_confusion(settings: Settings) -> None:
    """The null separator stops ambiguous concatenation.

    Without a separator that cannot appear in any field, identifier "ab" + code
    "123456" and identifier "ab1" + code "23456" would hash identically -- letting
    a code verify against the wrong identity.
    """
    a = hash_otp("123456", purpose=OtpPurpose.LOGIN_2FA, identifier="ab", settings=settings)
    b = hash_otp("23456", purpose=OtpPurpose.LOGIN_2FA, identifier="ab1", settings=settings)

    assert a != b


# ---------------------------------------------------------------------------
# Identifier normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["User@School.com", "  user@school.com  ", "USER@SCHOOL.COM", "user@school.com"],
)
def test_identifier_normalisation_is_stable(raw: str) -> None:
    """Requesting as `User@x.com` and submitting as `user@x.com` must still work."""
    assert normalise_identifier(raw) == "user@school.com"


def test_normalised_identifier_verifies_across_casing(settings: Settings) -> None:
    code = generate_otp()
    digest = hash_otp(
        code,
        purpose=OtpPurpose.PASSWORD_RESET,
        identifier=normalise_identifier("Admin@School.com"),
        settings=settings,
    )

    assert verify_otp(
        code,
        digest,
        purpose=OtpPurpose.PASSWORD_RESET,
        identifier=normalise_identifier("  admin@school.COM "),
        settings=settings,
    )
