"""
JWT authentication that can be revoked.

SimpleJWT's blacklist only revokes refresh tokens. Access tokens here last
three days, so "sign out everywhere" would leave the other device signed
in for three more days - which is not signing out at all.

Instead each profile can carry `tokens_valid_from`. A token issued before
that moment is refused, access and refresh alike, immediately - access
tokens here, refresh tokens in accounts/token_refresh.py (the refresh
endpoint never runs authentication, so it needs its own check).

For everyone who has never signed out everywhere the field is null and
this does nothing. The lookup is cached so the common case costs no query.
"""
import logging
from datetime import datetime, timezone as dt_timezone

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from pathzi.cache_utils import cache_get, cache_set

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 30
_NONE = "none"          # cached "this user has never revoked anything"


def valid_from_cache_key(user_id):
    return f"tokens_valid_from:{user_id}"


def tokens_valid_from(user):
    """When this user last signed out everywhere, or None."""
    key = valid_from_cache_key(user.id)
    cached = cache_get(key)
    if cached == _NONE:
        return None
    if cached is not None:
        return cached

    profile = getattr(user, "userprofile", None)
    if profile is None:
        from accounts.models import UserProfile
        profile = UserProfile.objects.filter(appuser=user).only("tokens_valid_from").first()

    value = getattr(profile, "tokens_valid_from", None) if profile else None
    cache_set(key, value if value is not None else _NONE, timeout=CACHE_TTL_SECONDS)
    return value


class SessionEnded(InvalidToken):
    """
    The token is genuine but its session was ended - by "sign out other
    devices", a password change or a password reset.

    Its own code so the app can go straight to the login screen: refreshing
    cannot help, because the refresh token belongs to the same ended session.
    Same status as any other invalid token.
    """
    default_detail = "Session ended. Please sign in again."
    default_code = "session_ended"


def ensure_session_not_ended(user, issued_at):
    """
    Raise SessionEnded if a token issued at `issued_at` predates the user's
    last revocation. The single rule for access AND refresh tokens - the
    refresh endpoint used to skip it, which let an ended device refresh its
    way back in.
    """
    cutoff = tokens_valid_from(user)
    if cutoff is None:
        return                               # never revoked - the usual case

    if issued_at is None:
        # A token with no issue time cannot be proved to be new enough.
        raise SessionEnded()

    issued = datetime.fromtimestamp(int(issued_at), tz=dt_timezone.utc)

    # iat is whole seconds; the cutoff has microseconds. Truncate the
    # cutoff so a token minted in the same second as the revocation -
    # the one we hand back to the device doing the signing out - is kept.
    if issued < cutoff.replace(microsecond=0):
        logger.info("Rejected a token issued before sign-out for user_id=%s", user.id)
        raise SessionEnded()


class RevocableJWTAuthentication(JWTAuthentication):
    """JWTAuthentication, plus: refuse tokens issued before a revocation."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        ensure_session_not_ended(user, validated_token.get("iat"))
        return user
