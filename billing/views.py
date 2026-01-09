# billing/views.py (add these helpers + updated status view)
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


def _get_invoice(subscription):
    inv = subscription.get("latest_invoice")
    inv_id = inv.get("id") if isinstance(inv, dict) else inv if isinstance(inv, str) else None
    if not inv_id:
        return None
    return stripe.Invoice.retrieve(inv_id, expand=["payment_intent"])


def _get_client_secret_from_invoice(invoice):
    if not invoice:
        return None, None
    hosted_url = invoice.get("hosted_invoice_url")
    pi = invoice.get("payment_intent")
    if not pi:
        return None, hosted_url
    if isinstance(pi, str):
        pi = stripe.PaymentIntent.retrieve(pi)
    return pi.get("client_secret"), hosted_url


def _sync_billing_from_stripe(billing: BillingProfile) -> BillingProfile:
    """
    Pull Stripe subscription truth and update local DB.
    Safe: does not overwrite current_period_end with None.
    """
    if not billing.stripe_subscription_id:
        return billing

    try:
        sub = stripe.Subscription.retrieve(billing.stripe_subscription_id)
    except Exception:
        return billing

    status = sub.get("status") or billing.subscription_status
    period_end = _ts_to_dt(sub.get("current_period_end"))

    changed = False
    if status and status != billing.subscription_status:
        billing.subscription_status = status
        changed = True

    if period_end is not None and period_end != billing.current_period_end:
        billing.current_period_end = period_end
        changed = True

    # Also self-heal missing customer id if needed
    cust_id = sub.get("customer")
    if cust_id and cust_id != billing.stripe_customer_id:
        billing.stripe_customer_id = cust_id
        changed = True

    if changed:
        billing.save(update_fields=["subscription_status", "current_period_end", "stripe_customer_id", "updated_at"])

    return billing


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile, _ = BillingProfile.objects.get_or_create(user=user)

        # If DB says active, still optionally sync once (rare drift)
        if profile.is_active and profile.stripe_subscription_id:
            profile = _sync_billing_from_stripe(profile)
            if profile.is_active:
                return Response({"detail": "You already have an active subscription."}, status=400)

        # 1) Customer
        if not profile.stripe_customer_id:
            customer = stripe.Customer.create(
                email=getattr(user, "email", None) or None,
                metadata={"user_id": str(user.id)},
            )
            profile.stripe_customer_id = customer["id"]
            profile.save(update_fields=["stripe_customer_id", "updated_at"])

        # 2) Ephemeral key for PaymentSheet
        eph_key = stripe.EphemeralKey.create(
            customer=profile.stripe_customer_id,
            stripe_version=settings.STRIPE_API_VERSION,
        )

        # 3) Reuse existing incomplete-ish subscription
        if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
            sub = stripe.Subscription.retrieve(
                profile.stripe_subscription_id,
                expand=["latest_invoice.payment_intent"],
            )

            invoice = _get_invoice(sub)
            client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

            if client_secret:
                return Response({
                    "customer_id": profile.stripe_customer_id,
                    "ephemeral_key_secret": eph_key["secret"],
                    "payment_intent_client_secret": client_secret,
                    "subscription_id": sub["id"],
                })

            if hosted_url:
                return Response({
                    "customer_id": profile.stripe_customer_id,
                    "ephemeral_key_secret": eph_key["secret"],
                    "subscription_id": sub["id"],
                    "hosted_invoice_url": hosted_url,
                    "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url to complete payment.",
                }, status=200)

            return Response({
                "detail": "No payable invoice / PaymentIntent found for this subscription.",
                "subscription_id": sub["id"],
            }, status=400)

        # 4) Create NEW subscription
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("X-Idempotency-Key")
            or f"subscribe:{user.id}:{uuid.uuid4()}"
        )

        sub = stripe.Subscription.create(
            customer=profile.stripe_customer_id,
            items=[{"price": settings.STRIPE_PRICE_ID_MONTHLY}],
            collection_method="charge_automatically",
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"],
            metadata={"user_id": str(user.id)},
            idempotency_key=idempotency_key,
        )

        profile.stripe_subscription_id = sub["id"]
        profile.subscription_status = sub.get("status", "incomplete")

        # Stripe may omit period_end until later; write only if present
        cpe = _ts_to_dt(sub.get("current_period_end"))
        if cpe is not None:
            profile.current_period_end = cpe

        profile.save(update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "current_period_end",
            "updated_at",
        ])

        invoice = _get_invoice(sub)
        client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

        if client_secret:
            return Response({
                "customer_id": profile.stripe_customer_id,
                "ephemeral_key_secret": eph_key["secret"],
                "payment_intent_client_secret": client_secret,
                "subscription_id": sub["id"],
            })

        if hosted_url:
            return Response({
                "customer_id": profile.stripe_customer_id,
                "ephemeral_key_secret": eph_key["secret"],
                "subscription_id": sub["id"],
                "hosted_invoice_url": hosted_url,
                "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url to complete payment.",
            }, status=200)

        return Response({
            "detail": "Stripe did not return PaymentIntent client_secret or hosted invoice url.",
            "subscription_id": sub["id"],
        }, status=400)


class SubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing:
            return Response({"is_active": False, "status": "none", "current_period_end": None})

        # ✅ Self-heal if missing period end (or you can also heal when status is incomplete/past_due)
        if billing.stripe_subscription_id and billing.current_period_end is None:
            billing = _sync_billing_from_stripe(billing)

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
