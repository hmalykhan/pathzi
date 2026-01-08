import uuid
import stripe

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BillingProfile

stripe.api_key = settings.STRIPE_SECRET_KEY


class SubscribeView(APIView):
    """
    Creates (or reuses) a Stripe Customer and Subscription, and returns:
    - customer_id
    - ephemeral_key_secret
    - payment_intent_client_secret (from subscription's first invoice)
    - subscription_id
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile, _ = BillingProfile.objects.get_or_create(user=user)

        # If already active, stop here
        if profile.is_active:
            return Response(
                {"detail": "You already have an active subscription."},
                status=400,
            )

        # 1) Create/reuse Stripe Customer
        if not profile.stripe_customer_id:
            customer = stripe.Customer.create(
                email=getattr(user, "email", None) or None,
                metadata={"user_id": str(user.id)},
            )
            profile.stripe_customer_id = customer["id"]
            profile.save(update_fields=["stripe_customer_id", "updated_at"])

        # 2) Create Ephemeral Key (required for PaymentSheet customer context)
        eph_key = stripe.EphemeralKey.create(
            customer=profile.stripe_customer_id,
            stripe_version=settings.STRIPE_API_VERSION,
        )

        # If we already have a subscription in incomplete/past_due, return the latest PI again
        if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
            sub = stripe.Subscription.retrieve(
                profile.stripe_subscription_id,
                expand=["latest_invoice.payment_intent"],
            )
            pi = (sub.get("latest_invoice") or {}).get("payment_intent")
            if not pi or not pi.get("client_secret"):
                return Response({"detail": "No payable invoice found."}, status=400)

            return Response({
                "customer_id": profile.stripe_customer_id,
                "ephemeral_key_secret": eph_key["secret"],
                "payment_intent_client_secret": pi["client_secret"],
                "subscription_id": sub["id"],
            })

        # 3) Create Subscription (first invoice has a PaymentIntent)
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("X-Idempotency-Key")
            or f"subscribe:{user.id}:{uuid.uuid4()}"
        )

        subscription = stripe.Subscription.create(
            customer=profile.stripe_customer_id,
            items=[{"price": settings.STRIPE_PRICE_ID_MONTHLY}],
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"],
            metadata={"user_id": str(user.id)},
            idempotency_key=idempotency_key,
        )

        # Update DB with subscription basics immediately
        profile.stripe_subscription_id = subscription["id"]
        profile.subscription_status = subscription.get("status", "incomplete")

        # current_period_end might be absent until active; keep if present
        cpe = subscription.get("current_period_end")
        if cpe:
            profile.current_period_end = timezone.datetime.fromtimestamp(cpe, tz=timezone.utc)

        profile.save(update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "current_period_end",
            "updated_at",
        ])

        pi = (subscription.get("latest_invoice") or {}).get("payment_intent")
        if not pi or not pi.get("client_secret"):
            return Response({"detail": "Stripe did not return a PaymentIntent client secret."}, status=500)

        return Response({
            "customer_id": profile.stripe_customer_id,
            "ephemeral_key_secret": eph_key["secret"],
            "payment_intent_client_secret": pi["client_secret"],
            "subscription_id": subscription["id"],
        })


class SubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing:
            return Response({"is_active": False, "status": "none", "current_period_end": None})

        return Response({
            "is_active": billing.is_active,
            "status": billing.subscription_status,
            "current_period_end": billing.current_period_end,
        })


class CustomerPortalView(APIView):
    """
    Returns a Stripe Customer Portal URL (open in WebView in Flutter).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_customer_id:
            return Response({"detail": "No Stripe customer found for this user."}, status=400)

        session = stripe.billing_portal.Session.create(
            customer=billing.stripe_customer_id,
            return_url=settings.BILLING_RETURN_URL,
        )

        return Response({"url": session["url"]})
