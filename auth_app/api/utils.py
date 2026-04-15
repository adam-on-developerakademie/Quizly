import logging
from datetime import datetime, timezone

from django.conf import settings
from rest_framework_simplejwt.exceptions import TokenError
from auth_app.models import RevokedToken


logger = logging.getLogger(__name__)


def exp_to_datetime(exp):
    """Convert JWT ``exp`` claim to UTC datetime."""
    if exp is None:
        return None
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def timestamp_to_datetime(value):
    """Convert a numeric timestamp to UTC datetime."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def get_token_time_info(raw_token, token_class):
    """Return normalized timing metadata for a JWT string."""
    if not raw_token:
        return {
            "issued_at": None,
            "expires_at": None,
            "remaining_seconds": None,
            "is_valid": False,
        }

    try:
        token = token_class(raw_token)
    except TokenError:
        return {
            "issued_at": None,
            "expires_at": None,
            "remaining_seconds": None,
            "is_valid": False,
        }

    issued_at_dt = timestamp_to_datetime(token.get("iat"))
    expires_at_dt = timestamp_to_datetime(token.get("exp"))
    now = datetime.now(timezone.utc)
    remaining_seconds = None
    if expires_at_dt is not None:
        remaining_seconds = max(int((expires_at_dt - now).total_seconds()), 0)

    return {
        "issued_at": issued_at_dt.isoformat() if issued_at_dt else None,
        "expires_at": expires_at_dt.isoformat() if expires_at_dt else None,
        "remaining_seconds": remaining_seconds,
        "is_valid": True,
    }


def revoke_token(raw_token, token_class, source_ip):
    """Persist token revocation and return token identity info if available."""
    if not raw_token:
        return None

    try:
        token = token_class(raw_token)
    except TokenError:
        return None

    token_jti = token.get("jti")
    user_id = token.get("user_id")
    expires_at = exp_to_datetime(token.get("exp"))

    if token_jti:
        RevokedToken.objects.get_or_create(
            jti=token_jti,
            defaults={
                "token_type": token.get("token_type", "unknown"),
                "user_id": user_id,
                "expires_at": expires_at,
                "source_ip": source_ip,
            },
        )

    return {"jti": token_jti, "user_id": user_id}


def set_auth_cookies(response, access_token=None, refresh_token=None):
    """Set HttpOnly auth cookies for access and/or refresh tokens."""
    cookie_secure = settings.JWT_COOKIE_SECURE

    if access_token:
        response.set_cookie(
            key="access_token",
            value=str(access_token),
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
        )

    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=str(refresh_token),
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
        )

    return response


def clear_auth_cookies(response):
    """Clear auth cookies by replacing them with empty, expired values."""
    cookie_secure = settings.JWT_COOKIE_SECURE

    response.set_cookie(
        key="access_token",
        value="",
        httponly=True,
        secure=cookie_secure,
        samesite="Lax",
        max_age=0,
    )
    response.set_cookie(
        key="refresh_token",
        value="",
        httponly=True,
        secure=cookie_secure,
        samesite="Lax",
        max_age=0,
    )

    return response
