"""
The referral screen's API (PART2_PAYMENTS.md section 5.2).

    POST /me/referral/codes/            a new single-use code to share
    POST /me/referral/invite            we email a new code
    GET  /me/referral                   the screen: joined, days earned, invites
    POST /me/referral/credits/{id}/ack/ the "you earned days" popup was shown
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import ReferralCredit
from billing.services import referrals

logger = logging.getLogger(__name__)


def _code_payload(referral):
    return {
        "id": referral.id,
        "code": referral.code,
        "channel": referral.channel,
        "email": referral.invited_email,
        "status": referral.status,
        "expires_at": referral.expires_at,
        "created_at": referral.created_at,
    }


class ReferralCodeCreateView(APIView):
    """POST /me/referral/codes/ - one fresh code per share."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            referral = referrals.create_code(request.user, channel="share")
        except referrals.ReferralError as e:
            return Response(
                {"status": False, "message": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"status": True, "message": "Referral code created.", "data": _code_payload(referral)},
            status=status.HTTP_201_CREATED,
        )


class ReferralInviteView(APIView):
    """POST /me/referral/invite - make a code and email it."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return Response(
                {"status": False, "message": "A valid email address is required.",
                 "code": "email_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            referral = referrals.create_code(request.user, channel="email", invited_email=email)
        except referrals.ReferralError as e:
            return Response(
                {"status": False, "message": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sender = request.user.get_full_name() or request.user.username
        # PLACEHOLDER WORDING - the project manager is supplying the real copy.
        subject = f"{sender} invited you to Pathzi"
        body = (
            f"Hi,\n\n"
            f"{sender} thinks Pathzi could help you find your career path.\n\n"
            f"Your invite code is: {referral.code}\n\n"
            f"Download Pathzi and enter this code when you sign up.\n\n"
            f"The code works once and expires in {referrals.CODE_EXPIRY_DAYS} days.\n\n"
            f"If you weren't expecting this, you can ignore this email.\n\n"
            f"- The Pathzi team"
        )

        sent = True
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
        except Exception as e:
            # The code is already made and valid, so the user can still copy
            # and send it themselves. Say so rather than pretending it went.
            sent = False
            logger.exception("Referral invite email failed for %s: %s", email, e)

        return Response(
            {
                "status": True,
                "message": "Invitation sent." if sent else
                           "Code created, but the email could not be sent. Share the code instead.",
                "data": {**_code_payload(referral), "email_sent": sent},
            },
            status=status.HTTP_201_CREATED,
        )


class ReferralSummaryView(APIView):
    """GET /me/referral - the whole referral screen in one call."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {"status": True, "message": "Referral summary.",
             "data": referrals.summary_for(request.user)},
            status=status.HTTP_200_OK,
        )


class ReferralCreditAckView(APIView):
    """POST /me/referral/credits/{id}/ack/ - the popup has been shown."""

    permission_classes = [IsAuthenticated]

    def post(self, request, credit_id):
        credit = ReferralCredit.objects.filter(id=credit_id, user=request.user).first()
        if credit is None:
            return Response(
                {"status": False, "message": "Credit not found.", "code": "credit_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if credit.seen_at is None:
            credit.seen_at = timezone.now()
            credit.save(update_fields=["seen_at"])

        return Response(
            {"status": True, "message": "Credit acknowledged."},
            status=status.HTTP_200_OK,
        )
