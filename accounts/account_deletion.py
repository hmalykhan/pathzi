"""
Deleting your own account, from inside the app.

Apple requires that an app which lets you create an account also lets you
delete it, without emailing anyone. See PART2_PAYMENTS.md section 5.5.

Two things this must get right:

1. Deleting the account does NOT cancel an Apple or Google subscription.
   Only the store can do that. So the response says whether a subscription
   is still running, and where to cancel it, and the app must show that
   before the account goes.
2. Deleting must not damage anyone else's data. A user's referral codes
   are kept (with the creator set to NULL) because the people who accepted
   those invitations still have credits pointing at them.
"""
import logging

from django.db import transaction

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserProfile
from billing.models import ReferralCode
from billing.services.revenuecat import manage_url_for

logger = logging.getLogger(__name__)


class DeleteMyAccountView(APIView):
    """
    DELETE /accounts/me/

    Deletes the signed-in account and everything belonging to it. The app
    is responsible for asking "are you sure?" first.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user

        # Gather this BEFORE deleting - afterwards there is nothing to read.
        billing = getattr(user, "billing", None)
        had_subscription = bool(billing and billing.is_active)
        store = billing.store if billing else None
        user_id, username = user.id, user.username

        with transaction.atomic():
            # Their contacts' email addresses are not theirs to leave behind,
            # but the code rows themselves must stay: other people's credits
            # point at them.
            ReferralCode.objects.filter(created_by=user).update(invited_email=None)

            profile = UserProfile.objects.filter(appuser=user).first()
            if profile is not None:
                profile.delete()

            user.delete()

        logger.info("Account deleted: user_id=%s username=%s", user_id, username)

        message = "Your account has been deleted."
        if had_subscription:
            message = (
                "Your account has been deleted. Your subscription is still "
                "active - cancel it in the store, or you will keep being charged."
            )

        return Response(
            {
                "status": True,
                "message": message,
                "data": {
                    "deleted": True,
                    # The app must show this: we cannot cancel a store
                    # subscription on the user's behalf.
                    "had_active_subscription": had_subscription,
                    "store": store,
                    "manage_url": manage_url_for(store) if had_subscription else None,
                },
            },
            status=200,
        )
