# billing/views.py
import uuid
import stripe

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BillingProfile
from .utils import subscription_period_end_dt

stripe.api_key = settings.STRIPE_SECRET_KEY


def _get_invoice(subscription):
    inv = subscription.get("latest_invoice")
    inv_id = None
    if isinstance(inv, dict):
        inv_id = inv.get("id")
    elif isinstance(inv, str):
        inv_id = inv

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
    Self-heal local BillingProfile by pulling Stripe subscription truth.
    Uses item-level period end fallback if top-level is missing.
    """
    if not billing.stripe_subscription_id:
        return billing

    try:
        sub = stripe.Subscription.retrieve(billing.stripe_subscription_id, expand=["items"])
    except Exception:
        return billing

    status = sub.get("status") or billing.subscription_status
    period_end = subscription_period_end_dt(sub)
    customer_id = sub.get("customer") or billing.stripe_customer_id

    changed = False

    if status and status != billing.subscription_status:
        billing.subscription_status = status
        changed = True

    if period_end is not None and period_end != billing.current_period_end:
        billing.current_period_end = period_end
        changed = True

    if customer_id and customer_id != billing.stripe_customer_id:
        billing.stripe_customer_id = customer_id
        changed = True

    if changed:
        billing.save(update_fields=["subscription_status", "current_period_end", "stripe_customer_id", "updated_at"])

    return billing


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile, _ = BillingProfile.objects.get_or_create(user=user)

        # Already active (optional sync to prevent drift)
        if profile.is_active and profile.stripe_subscription_id:
            profile = _sync_billing_from_stripe(profile)
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

        # 2) Ephemeral Key
        eph_key = stripe.EphemeralKey.create(
            customer=profile.stripe_customer_id,
            stripe_version=settings.STRIPE_API_VERSION,
        )

        # 3) If existing incomplete subscription → reuse it
        if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
            sub = stripe.Subscription.retrieve(
                profile.stripe_subscription_id,
                expand=["latest_invoice.payment_intent", "items"],
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
                    "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment.",
                }, status=200)

            return Response({
                "detail": "No payable invoice / PaymentIntent found. Check Stripe → Invoice for this subscription.",
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
            expand=["latest_invoice.payment_intent", "items"],
            metadata={"user_id": str(user.id)},
            idempotency_key=idempotency_key,
        )

        profile.stripe_subscription_id = sub["id"]
        profile.subscription_status = sub.get("status", "incomplete")

        # ✅ item-level fallback
        cpe = subscription_period_end_dt(sub)
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
                "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment.",
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

        # ✅ Self-heal if missing period end OR if status could be stale
        if billing.stripe_subscription_id and (billing.current_period_end is None):
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


class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_subscription_id:
            return Response({"detail": "No subscription found."}, status=400)

        # recommended: cancel at period end
        cancel_at_period_end = bool(request.data.get("cancel_at_period_end", True))

        sub = stripe.Subscription.modify(
            billing.stripe_subscription_id,
            cancel_at_period_end=cancel_at_period_end,
            expand=["items"],
        )

        # update local db (status can remain active until period end)
        billing.subscription_status = sub.get("status") or billing.subscription_status
        pe = subscription_period_end_dt(sub)
        if pe is not None:
            billing.current_period_end = pe
        billing.save(update_fields=["subscription_status", "current_period_end", "updated_at"])

        return Response({
            "status": sub.get("status"),
            "cancel_at_period_end": sub.get("cancel_at_period_end"),
            "current_period_end": billing.current_period_end,
        })