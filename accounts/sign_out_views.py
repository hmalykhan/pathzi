"""
Sign out other devices.

Marks a moment on the profile; every token issued before it is refused
from then on - access and refresh alike, immediately. See
accounts/authentication.py for why this is not SimpleJWT's blacklist.

The device doing the signing out gets a fresh pair back, so the user is
not logged out of the phone they are holding.
"""
import logging

from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import UserProfile
from accounts.authentication import valid_from_cache_key
from pathzi.cache_utils import cache_delete

logger = logging.getLogger(__name__)


def revoke_all_tokens(user, *, keep_current=True):
    """
    End every session for this user.

    Returns a fresh token pair when `keep_current`, so the device asking to
    sign the others out stays signed in.
    """
    profile, _ = UserProfile.objects.get_or_create(appuser=user)
    profile.tokens_valid_from = timezone.now()
    profile.save(update_fields=["tokens_valid_from"])

    # The authentication layer caches this; it must not serve the old value.
    cache_delete(valid_from_cache_key(user.id))

    logger.info("All sessions ended for user_id=%s", user.id)

    if not keep_current:
        return None

    # Minted after the cutoff, so this one survives it.
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class SignOutOtherDevicesView(APIView):
    """
    POST /accounts/sign-out-other-devices/

    Ends every other session at once. The caller is handed a new token
    pair and stays signed in.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = revoke_all_tokens(request.user, keep_current=True)
        return Response(
            {
                "status": True,
                "message": "Signed out on all other devices.",
                "data": {"token": token},
            },
            status=200,
        )
