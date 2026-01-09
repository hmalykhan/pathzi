import uuid
import stripe

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BillingProfile

stripe.api_key = settings.STRIPE_SECRET_KEY


def _ts_to_dt(ts):
    if not ts:
        return None
    return timezone.datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _get_pi_client_secret_from_subscription(sub_id: str):
    """
    Always fetch latest invoice -> finalize if draft -> expand payment_intent -> return client_secret.
    Returns (client_secret, amount_due) where client_secret can be None.
    """
    # Get subscription (latest_invoice may be id or object)
    sub = stripe.Subscription.retrieve(sub_id, expand=["latest_invoice"])
    latest_invoice = sub.get("latest_invoice")

    # If subscription.latest_invoice is missing, fallback to list invoices
    if not latest_invoice:
        inv_list = stripe.Invoice.list(subscription=sub_id, limit=1)
        latest_invoice = inv_list.data[0] if inv_list.data else None

    if not latest_invoice:
        return None, None

    inv_id = latest_invoice if isinstance(latest_invoice, str) else latest_invoice.get("id")
    inv = stripe.Invoice.retrieve(inv_id, expand=["payment_intent"])

    # If invoice is draft, finalize to generate PI in many cases
    if inv.get("status") == "draft":
        inv = stripe.Invoice.finalize_invoice(inv_id, expand=["payment_intent"])

    amount_due = inv.get("amount_due")
    pi = inv.get("payment_intent")

    if not pi:
        return None, amount_due

    # PI can be id string or expanded object
    if isinstance(pi, str):
        pi = stripe.PaymentIntent.retrieve(pi)

    return pi.get("client_secret"), amount_due


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile, _ = BillingProfile.objects.get_or_create(user=user)

        if profile.is_active:
            return Response({"detail": "You already have an active subscription."}, status=400)

        # 1) Create/reuse Stripe Customer
        if not profile.stripe_customer_id:
            customer = stripe.Customer.create(
                email=getattr(user, "email", None) or None,
                metadata={"user_id": str(user.id)},
            )
            profile.stripe_customer_id = customer["id"]
            profile.save(update_fields=["stripe_customer_id", "updated_at"])

        # 2) Ephemeral key
        eph_key = stripe.EphemeralKey.create(
            customer=profile.stripe_customer_id,
            stripe_version=settings.STRIPE_API_VERSION,
        )

        # 3) If an existing subscription is incomplete, reuse it and return PI secret
        if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
            client_secret, amount_due = _get_pi_client_secret_from_subscription(profile.stripe_subscription_id)

            if amount_due == 0:
                return Response(
                    {"detail": "Invoice amount is 0. Check if price is free or discounted to 0."},
                    status=400,
                )

            if not client_secret:
                return Response(
                    {"detail": "No payable invoice/PaymentIntent found. Check Stripe invoice status for this subscription."},
                    status=400,
                )

            return Response({
                "customer_id": profile.stripe_customer_id,
                "ephemeral_key_secret": eph_key["secret"],
                "payment_intent_client_secret": client_secret,
                "subscription_id": profile.stripe_subscription_id,
            })

        # 4) Create a new subscription
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("X-Idempotency-Key")
            or f"subscribe:{user.id}:{uuid.uuid4()}"
        )

        sub = stripe.Subscription.create(
            customer=profile.stripe_customer_id,
            items=[{"price": settings.STRIPE_PRICE_ID_MONTHLY}],
            collection_method="charge_automatically",  # important
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            metadata={"user_id": str(user.id)},
            idempotency_key=idempotency_key,
        )

        # Save subscription to DB
        profile.stripe_subscription_id = sub["id"]
        profile.subscription_status = sub.get("status", "incomplete")
        cpe = sub.get("current_period_end")
        profile.current_period_end = _ts_to_dt(cpe) if cpe else None
        profile.save(update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "current_period_end",
            "updated_at",
        ])

        # Now fetch invoice -> PI secret (reliable)
        client_secret, amount_due = _get_pi_client_secret_from_subscription(sub["id"])

        if amount_due == 0:
            return Response(
                {"detail": "Invoice amount is 0. Check if price is free or discounted to 0."},
                status=400,
            )

        if not client_secret:
            return Response(
                {"detail": "Stripe did not return a PaymentIntent client secret. Check subscription's latest invoice in Stripe."},
                status=400,
            )

        return Response({
            "customer_id": profile.stripe_customer_id,
            "ephemeral_key_secret": eph_key["secret"],
            "payment_intent_client_secret": client_secret,
            "subscription_id": sub["id"],
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
