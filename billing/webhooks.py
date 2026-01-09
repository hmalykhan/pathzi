# billing/webhooks.py
import json
import stripe
from datetime import datetime, timezone as dt_timezone

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
        return  # nothing to update

    update_fields = {"updated_at": timezone.now()}

    if sub_id:
        update_fields["stripe_subscription_id"] = sub_id

    if status is not None:
        update_fields["subscription_status"] = status

    # ✅ only write if we actually have a value
    if period_end is not None:
        update_fields["current_period_end"] = period_end

    qs.update(**update_fields)


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

        period_end = _ts_to_dt(obj.get("current_period_end"))

        # ✅ If Stripe didn't include it in event, fetch subscription once
        if period_end is None and sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                period_end = _ts_to_dt(sub.get("current_period_end"))
            except Exception:
                pass

        _update_billing(
            sub_id=sub_id,
            customer_id=customer_id,
            status=status,
            period_end=period_end,
        )

    # ---- Payment outcomes ----
    elif event_type == "invoice.paid":
        sub_id = obj.get("subscription")
        if sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                _update_billing(
                    sub_id=sub_id,
                    customer_id=sub.get("customer"),
                    status=sub.get("status", "active"),
                    period_end=_ts_to_dt(sub.get("current_period_end")),
                )
            except Exception:
                pass

    elif event_type in ("invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = obj.get("subscription")
        if sub_id:
            _update_billing(sub_id=sub_id, status="past_due")

    return HttpResponse(status=200)
