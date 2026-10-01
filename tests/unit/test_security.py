"""Sign-in codes, JWT access tokens (P2.1) and CSRF tokens (P2.4)."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    csrf_tokens_match,
    decode_access_token,
    generate_csrf_token,
    generate_login_code,
    hash_login_code,
    login_code_matches,
)

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SECRET = get_settings().jwt_secret


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _sign(claims: dict, key: str = SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm)


def _claims(**overrides) -> dict:
    claims = {"sub": "7", "iat": NOW, "exp": NOW + timedelta(hours=1)}
    claims.update(overrides)
    return claims


# --- sign-in codes ---------------------------------------------------------


def test_a_code_is_six_digits_including_leading_zeros(monkeypatch):
    monkeypatch.setattr("app.core.security.secrets.randbelow", lambda n: 4217)

    assert generate_login_code() == "004217"


def test_generated_codes_are_always_six_digits_and_vary():
    codes = {generate_login_code() for _ in range(200)}

    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # not a constant


def test_a_code_matches_its_hash_for_the_same_email_only():
    stored = hash_login_code("a@example.com", "123456")

    assert login_code_matches("a@example.com", "123456", stored) is True
    assert login_code_matches("a@example.com", "123457", stored) is False
    assert login_code_matches("b@example.com", "123456", stored) is False


def test_the_hash_does_not_contain_the_code_and_depends_on_the_secret(monkeypatch):
    stored = hash_login_code("a@example.com", "123456")
    assert "123456" not in stored and len(stored) == 64

    other = get_settings().model_copy(update={"jwt_secret": "another-secret-entirely"})
    monkeypatch.setattr("app.core.security.get_settings", lambda: other)
    assert hash_login_code("a@example.com", "123456") != stored


# --- tokens ----------------------------------------------------------------


def test_token_round_trip_returns_the_user_id():
    assert decode_access_token(create_access_token(7, NOW), NOW) == 7


def test_token_carries_sub_iat_and_exp():
    claims = jwt.decode(
        create_access_token(7, NOW),
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    minutes = get_settings().jwt_expire_minutes
    assert claims == {
        "sub": "7",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=minutes)).timestamp()),
    }


def test_token_is_valid_until_the_instant_it_expires():
    token = create_access_token(7, NOW)
    lifetime = timedelta(minutes=get_settings().jwt_expire_minutes)

    assert decode_access_token(token, NOW + lifetime - timedelta(seconds=1)) == 7

    with pytest.raises(InvalidTokenError) as caught:
        decode_access_token(token, NOW + lifetime)
    assert caught.value.code == "TOKEN_EXPIRED"
    assert caught.value.status_code == 401


def test_tampered_payload_is_rejected():
    header, _, signature = create_access_token(7, NOW).split(".")
    forged_payload = _b64({"sub": "1", "iat": 0, "exp": 9999999999})  # try to become user 1
    with pytest.raises(InvalidTokenError) as caught:
        decode_access_token(f"{header}.{forged_payload}.{signature}", NOW)
    assert caught.value.code == "INVALID_TOKEN"


def test_token_signed_with_another_secret_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(), key="some-other-secret-of-sufficient-length"), NOW)


def test_alg_none_token_is_rejected():
    unsigned = (
        f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': '1', 'iat': 0, 'exp': 9999999999})}."
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, NOW)


# PyJWT warns that the short test secret is weak for HS384; irrelevant here.
@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_token_with_another_algorithm_is_rejected():
    # Correctly signed with the right secret, but not the algorithm we allow.
    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(), algorithm="HS384"), NOW)


@pytest.mark.parametrize("missing", ["sub", "iat", "exp"])
def test_token_missing_a_required_claim_is_rejected(missing):
    claims = _claims()
    del claims[missing]
    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(claims), NOW)


def test_signed_token_with_a_non_numeric_subject_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(sub="admin")), NOW)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "not a jwt at all"])
def test_malformed_token_is_rejected(garbage):
    with pytest.raises(InvalidTokenError):
        decode_access_token(garbage, NOW)


# --- CSRF tokens -----------------------------------------------------------


def test_csrf_tokens_are_random_and_long_enough():
    first, second = generate_csrf_token(), generate_csrf_token()
    assert first != second
    assert len(first) >= 32


def test_matching_csrf_tokens_match():
    token = generate_csrf_token()
    assert csrf_tokens_match(token, token) is True


def test_different_csrf_tokens_do_not_match():
    assert csrf_tokens_match("abc", "abd") is False
    assert csrf_tokens_match("abc", "abcd") is False


@pytest.mark.parametrize("cookie,submitted", [(None, None), ("", ""), (None, ""), ("abc", None)])
def test_missing_or_empty_csrf_tokens_never_match(cookie, submitted):
    """Two empty values are equal, but 'no cookie and no header' must not pass."""
    assert csrf_tokens_match(cookie, submitted) is False


def test_non_ascii_csrf_token_is_a_mismatch_not_a_crash():
    assert csrf_tokens_match("abc", "abç") is False
