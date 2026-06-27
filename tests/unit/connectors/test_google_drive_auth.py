from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pidgin.connectors.google_drive.auth import (
    GOOGLE_TOKEN_URL,
    ServiceAccountError,
    _build_assertion,
)


def _service_account() -> tuple[dict[str, str], str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    sa = {"client_email": "svc@acme.iam.gserviceaccount.com", "private_key": private_pem}
    return sa, public_pem


def test_assertion_includes_delegated_user() -> None:
    sa, public_pem = _service_account()
    now = int(time.time())
    token = _build_assertion(
        sa, scope="https://scope", delegated_user="user@acme.com", now=now
    )
    claims = jwt.decode(token, public_pem, algorithms=["RS256"], audience=GOOGLE_TOKEN_URL)
    assert claims["iss"] == sa["client_email"]
    assert claims["sub"] == "user@acme.com"
    assert claims["scope"] == "https://scope"
    assert claims["exp"] == now + 3600


def test_assertion_omits_sub_without_delegation() -> None:
    sa, public_pem = _service_account()
    token = _build_assertion(sa, scope="s", delegated_user=None, now=int(time.time()))
    claims = jwt.decode(token, public_pem, algorithms=["RS256"], audience=GOOGLE_TOKEN_URL)
    assert "sub" not in claims


def test_assertion_missing_fields_raises() -> None:
    with pytest.raises(ServiceAccountError, match="client_email or private_key"):
        _build_assertion({"client_email": "x"}, scope="s", delegated_user=None, now=0)
