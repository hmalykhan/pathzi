# billing/webhooks.py
import json
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
    return timezone.datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _json_safe(obj):
    """
    Make Stripe objects JSON-safe for storing in JSONField.
    """
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = settings.STRIPE_WEBHOOK_SECRET

    # 1) Verify signature
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    # 2) De-dupe (race-safe)
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

    # 3) Handle events
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        sub_id = obj.get("id")
        status = obj.get("status") or "none"
        customer_id = obj.get("customer")
        period_end = _ts_to_dt(obj.get("current_period_end"))

        qs = BillingProfile.objects.filter(stripe_subscription_id=sub_id)
        if not qs.exists() and customer_id:
            qs = BillingProfile.objects.filter(stripe_customer_id=customer_id)

        qs.update(
            stripe_subscription_id=sub_id,
            subscription_status=status,
            current_period_end=period_end,
            updated_at=timezone.now(),
        )

    elif event_type == "customer.subscription.deleted":
        sub_id = obj.get("id")
        BillingProfile.objects.filter(stripe_subscription_id=sub_id).update(
            subscription_status="canceled",
            updated_at=timezone.now(),
        )

    elif event_type == "invoice.paid":
        sub_id = obj.get("subscription")
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            BillingProfile.objects.filter(stripe_subscription_id=sub_id).update(
                subscription_status=sub.get("status", "active"),
                current_period_end=_ts_to_dt(sub.get("current_period_end")),
                updated_at=timezone.now(),
            )

    elif event_type == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        if sub_id:
            BillingProfile.objects.filter(stripe_subscription_id=sub_id).update(
                subscription_status="past_due",
                updated_at=timezone.now(),
            )

    elif event_type == "invoice.payment_action_required":
        # Renewal requires customer action (3DS/SCA). Treat as not-active until resolved.
        sub_id = obj.get("subscription")
        if sub_id:
            BillingProfile.objects.filter(stripe_subscription_id=sub_id).update(
                subscription_status="past_due",
                updated_at=timezone.now(),
            )

    return HttpResponse(status=200)
