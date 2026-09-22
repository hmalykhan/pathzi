"""
POST /accounts/api/token/refresh/ that respects ended sessions.

SimpleJWT's refresh view runs no authentication, so the revocation check in
accounts/authentication.py never saw refresh tokens. A device signed out by
"sign out other devices", a password change or a password reset could post
its old refresh token here, get a brand-new access token - issued after the
cutoff, so it passed every later check - and stay signed in indefinitely.

Wired in through SIMPLE_JWT["TOKEN_REFRESH_SERIALIZER"], so the URL, the
view and the response for every live session are unchanged.
"""
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from accounts.authentication import ensure_session_not_ended


class RevocableTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        # Signature and expiry first - a forged or expired token must fail
        # exactly as before, not reach the session check.
        refresh = self.token_class(attrs["refresh"])

        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        if user_id:
            user = get_user_model().objects.filter(
                **{api_settings.USER_ID_FIELD: user_id}
            ).first()
            if user is not None:
                ensure_session_not_ended(user, refresh.payload.get("iat"))

        return super().validate(attrs)
