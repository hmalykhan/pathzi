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


def _update_billing_profile_by_sub_or_customer(*, sub_id=None, customer_id=None, **fields):
    """
    Update BillingProfile safely.
    - Finds BillingProfile by subscription_id first; if not found and customer_id exists, falls back to customer_id.
    - Does NOT overwrite current_period_end with None.
    """
    qs = BillingProfile.objects.none()

    if sub_id:
        qs = BillingProfile.objects.filter(stripe_subscription_id=sub_id)

    if (not qs.exists()) and customer_id:
        qs = BillingProfile.objects.filter(stripe_customer_id=customer_id)

    if not qs.exists():
        return  # nothing to update

    # Don't overwrite existing period end with None
    if "current_period_end" in fields and fields["current_period_end"] is None:
        fields.pop("current_period_end", None)

    fields["updated_at"] = timezone.now()
    qs.update(**fields)


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
    obj = event["data"]["object"]  # Stripe object payload

    # ------------------------------
    # Subscription state sync
    # ------------------------------
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        sub_id = obj.get("id")
        status = obj.get("status") or "none"
        customer_id = obj.get("customer")
        period_end = _ts_to_dt(obj.get("current_period_end"))

        _update_billing_profile_by_sub_or_customer(
            sub_id=sub_id,
            customer_id=customer_id,
            stripe_subscription_id=sub_id,
            subscription_status=status,
            current_period_end=period_end,
        )

    elif event_type == "customer.subscription.deleted":
        sub_id = obj.get("id")
        customer_id = obj.get("customer")

        _update_billing_profile_by_sub_or_customer(
            sub_id=sub_id,
            customer_id=customer_id,
            subscription_status="canceled",
        )

    # ------------------------------
    # Payment outcomes (renewals + first payment)
    # ------------------------------
    elif event_type == "invoice.paid":
        sub_id = obj.get("subscription")
        customer_id = obj.get("customer")

        # Fetch authoritative subscription to get correct period end + status
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            status = sub.get("status") or "active"
            period_end = _ts_to_dt(sub.get("current_period_end"))

            _update_billing_profile_by_sub_or_customer(
                sub_id=sub_id,
                customer_id=customer_id,
                subscription_status=status,
                current_period_end=period_end,
            )

    elif event_type in ("invoice.payment_failed", "invoice.payment_action_required"):
        # Renewal needs action or failed -> treat as not active
        sub_id = obj.get("subscription")
        customer_id = obj.get("customer")

        if sub_id:
            _update_billing_profile_by_sub_or_customer(
                sub_id=sub_id,
                customer_id=customer_id,
                subscription_status="past_due",
            )

    return HttpResponse(status=200)
