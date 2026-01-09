# billing/webhooks.py
import json
from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import BillingProfile, StripeEvent

stripe.api_key = settings.STRIPE_SECRET_KEY


def _ts_to_dt(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=dt_timezone.utc)


def _json_safe(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


def _retrieve_subscription(sub_id: str):
    try:
        return stripe.Subscription.retrieve(sub_id)
    except Exception:
        return None


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

    if period_end is not None:
        update_fields["current_period_end"] = period_end

    qs.update(**update_fields)


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    # De-dupe
    _, created = StripeEvent.objects.get_or_create(
        event_id=event["id"],
        defaults={"event_type": event["type"], "payload": _json_safe(event)},
    )
    if not created:
        return HttpResponse(status=200)

    event_type = event["type"]
    obj = event["data"]["object"]

    # ---- subscription.* ----
    if event_type.startswith("customer.subscription."):
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        status = obj.get("status") or "none"
        period_end = _ts_to_dt(obj.get("current_period_end"))

        # If missing, retrieve subscription once
        if period_end is None and sub_id:
            sub = _retrieve_subscription(sub_id)
            if sub:
                period_end = _ts_to_dt(sub.get("current_period_end"))
                customer_id = customer_id or sub.get("customer")
                status = sub.get("status") or status

        _update_billing(sub_id=sub_id, customer_id=customer_id, status=status, period_end=period_end)
        return HttpResponse(status=200)

    # ---- invoice paid/failed/action_required ----
    if event_type in ("invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = obj.get("subscription")
        if not sub_id:
            return HttpResponse(status=200)

        sub = _retrieve_subscription(sub_id)
        if not sub:
            return HttpResponse(status=200)

        status = sub.get("status") or "none"
        period_end = _ts_to_dt(sub.get("current_period_end"))
        customer_id = sub.get("customer")

        # If payment failed/action required, Stripe status may still be active sometimes.
        # Your gating uses DB is_active; we keep Stripe truth as primary.
        _update_billing(sub_id=sub_id, customer_id=customer_id, status=status, period_end=period_end)
        return HttpResponse(status=200)

    return HttpResponse(status=200)
