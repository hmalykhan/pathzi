# billing/webhooks.py
import json
import stripe

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import BillingProfile, StripeEvent
from .utils import subscription_period_end_dt

stripe.api_key = settings.STRIPE_SECRET_KEY


def _json_safe(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


def _update_billing(*, sub_id=None, customer_id=None, status=None, period_end=None):
    """
    Update BillingProfile without ever overwriting current_period_end with None.
    """
    qs = BillingProfile.objects.none()

    if sub_id:
        qs = BillingProfile.objects.filter(stripe_subscription_id=sub_id)

    if (not qs.exists()) and customer_id:
        qs = BillingProfile.objects.filter(stripe_customer_id=customer_id)

    if not qs.exists():
        return

    update_fields = {"updated_at": timezone.now()}

    if sub_id:
        update_fields["stripe_subscription_id"] = sub_id

    if status is not None:
        update_fields["subscription_status"] = status

    # ✅ only write if we actually have a value
    if period_end is not None:
        update_fields["current_period_end"] = period_end

    qs.update(**update_fields)


def _retrieve_subscription(sub_id: str):
    try:
        # items are included by default, but we keep it explicit
        return stripe.Subscription.retrieve(sub_id, expand=["items"])
    except Exception:
        return None


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    # De-dupe (race-safe)
    _, created = StripeEvent.objects.get_or_create(
        event_id=event["id"],
        defaults={
            "event_type": event["type"],
            "payload": _json_safe(event),
        },
    )
    if not created:
        return HttpResponse(status=200)

    event_type = event["type"]
    obj = event["data"]["object"]

    # ---- Subscription state sync ----
    if event_type.startswith("customer.subscription."):
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        status = obj.get("status") or "none"

        # ✅ Works for both legacy and item-level period end
        period_end = subscription_period_end_dt(obj)

        # ✅ If Stripe didn't include items in this event payload, fetch subscription once
        if period_end is None and sub_id:
            sub = _retrieve_subscription(sub_id)
            if sub:
                period_end = subscription_period_end_dt(sub)
                customer_id = customer_id or sub.get("customer")
                status = sub.get("status") or status

        _update_billing(
            sub_id=sub_id,
            customer_id=customer_id,
            status=status,
            period_end=period_end,
        )

        return HttpResponse(status=200)

    # ---- Payment outcomes ----
    if event_type in ("invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = obj.get("subscription")
        if not sub_id:
            return HttpResponse(status=200)

        sub = _retrieve_subscription(sub_id)
        if not sub:
            return HttpResponse(status=200)

        _update_billing(
            sub_id=sub_id,
            customer_id=sub.get("customer"),
            status=sub.get("status", "none"),
            period_end=subscription_period_end_dt(sub),
        )
        return HttpResponse(status=200)

    return HttpResponse(status=200)
