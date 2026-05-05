


# billing/webhooks.py
import json
import stripe

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from stripe import error as stripe_error

from .models import BillingProfile, StripeEvent
from .utils import subscription_period_end_dt, ts_to_dt

# Stripe (api_key + http_client timeout) is configured once in billing.apps.BillingConfig.ready().

_MISSING = object()


# def _json_safe(obj):
#     try:
#         return json.loads(json.dumps(obj, default=str))
#     except Exception:
#         return {"raw": str(obj)}

def _json_safe(obj):
    try:
        # 👇 only add this small guard
        if hasattr(obj, "_to_dict_recursive"):
            obj = obj._to_dict_recursive()

        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


def _subscription_price_id(sub_obj):
    """
    Returns the Stripe Price ID from a Subscription object (dict).
    Handles both expanded and non-expanded price shapes.

    NOTE: Slightly safer than items[0] only: we pick the first item with a usable price id.
    """
    items = (sub_obj.get("items") or {}).get("data") or []
    for item in items:
        price = item.get("price")
        if isinstance(price, str) and price:
            return price
        if isinstance(price, dict) and price.get("id"):
            return price.get("id")
    return None


def _plan_id_from_price_id(price_id: str | None):
    if not price_id:
        return None
    for plan_id, cfg in getattr(settings, "STRIPE_PLANS", {}).items():
        if cfg.get("price_id") == price_id:
            return plan_id
    return None


def _update_billing(
    *,
    sub_id=None,
    customer_id=None,
    status=None,
    period_end=None,
    plan_id=_MISSING,
    stripe_price_id=_MISSING,
    pending_plan_id=_MISSING,
    pending_change_at=_MISSING,
    stripe_schedule_id=_MISSING,
):
    """
    Update BillingProfile without overwriting fields unless we explicitly intend to.
    Use _MISSING sentinel to mean "don't touch this field".
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

    if plan_id is not _MISSING:
        update_fields["plan_id"] = plan_id
    if stripe_price_id is not _MISSING:
        update_fields["stripe_price_id"] = stripe_price_id

    if pending_plan_id is not _MISSING:
        update_fields["pending_plan_id"] = pending_plan_id
    if pending_change_at is not _MISSING:
        update_fields["pending_change_at"] = pending_change_at
    if stripe_schedule_id is not _MISSING:
        update_fields["stripe_schedule_id"] = stripe_schedule_id

    qs.update(**update_fields)


def _retrieve_subscription(sub_id: str):
    try:
        # keep expand minimal; items is enough for price id
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
    except (ValueError, stripe_error.SignatureVerificationError):
        return HttpResponse(status=400)

    # De-dupe (race safe)
    try:
        _, created = StripeEvent.objects.get_or_create(
            event_id=event["id"],
            defaults={"event_type": event["type"], "payload": _json_safe(event)},

        )
    except IntegrityError:
        return HttpResponse(status=200)

    if not created:
        return HttpResponse(status=200)

    event_type = event["type"]
    obj = event["data"]["object"]

    # -----------------------------
    # SubscriptionSchedule events (downgrades)
    # -----------------------------
    if event_type.startswith("subscription_schedule."):
        sched = obj
        sub_id = sched.get("subscription")
        phases = sched.get("phases") or []

        pending_plan = None
        pending_at = None

        if len(phases) > 1:
            next_phase = phases[1]
            items = next_phase.get("items") or []
            if items:
                price = items[0].get("price")
                price_id = price.get("id") if isinstance(price, dict) else (price if isinstance(price, str) else None)
                pending_plan = _plan_id_from_price_id(price_id)
            pending_at = ts_to_dt(next_phase.get("start_date"))

        if sub_id:
            _update_billing(
                sub_id=sub_id,
                stripe_schedule_id=sched.get("id"),
                pending_plan_id=pending_plan,
                pending_change_at=pending_at,
            )

        # Clear schedule info when it ends/releases
        if event_type in (
            "subscription_schedule.released",
            "subscription_schedule.canceled",
            "subscription_schedule.completed",
        ) and sub_id:
            _update_billing(
                sub_id=sub_id,
                pending_plan_id=None,
                pending_change_at=None,
                stripe_schedule_id=None,
            )

        return HttpResponse(status=200)

    # -----------------------------
    # customer.subscription.* events
    # -----------------------------
    if event_type.startswith("customer.subscription."):
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        status = obj.get("status") or "none"

        period_end = subscription_period_end_dt(obj)
        price_id = _subscription_price_id(obj)
        plan_id = _plan_id_from_price_id(price_id)

        pending_update = obj.get("pending_update")

        # Fetch full subscription only when needed
        if sub_id and (period_end is None or price_id is None or pending_update is None):
            sub = _retrieve_subscription(sub_id)
            if sub:
                period_end = period_end or subscription_period_end_dt(sub)
                customer_id = customer_id or sub.get("customer")
                status = sub.get("status") or status
                price_id = price_id or _subscription_price_id(sub)
                plan_id = plan_id or _plan_id_from_price_id(price_id)
                if pending_update is None:
                    pending_update = sub.get("pending_update")

        clear_pending = not bool(pending_update)

        # IMPORTANT FIX:
        # If Stripe gave us a price_id, we also write plan_id derived from it (even if None).
        plan_field = plan_id if price_id is not None else _MISSING
        price_field = price_id if price_id is not None else _MISSING

        _update_billing(
            sub_id=sub_id,
            customer_id=customer_id,
            status=status,
            period_end=period_end,
            plan_id=plan_field,
            stripe_price_id=price_field,
            pending_plan_id=None if clear_pending else _MISSING,
            pending_change_at=None if clear_pending else _MISSING,
            # IMPORTANT: don't wipe stripe_schedule_id here
        )
        return HttpResponse(status=200)

    # -----------------------------
    # Invoice events (payment state)
    # -----------------------------
    if event_type in ("invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = obj.get("subscription")
        if not sub_id:
            return HttpResponse(status=200)

        sub = _retrieve_subscription(sub_id)
        if not sub:
            return HttpResponse(status=200)

        price_id = _subscription_price_id(sub)
        plan_id = _plan_id_from_price_id(price_id)

        clear_pending = not bool(sub.get("pending_update"))

        # IMPORTANT FIX: same rule here
        plan_field = plan_id if price_id is not None else _MISSING
        price_field = price_id if price_id is not None else _MISSING

        _update_billing(
            sub_id=sub_id,
            customer_id=sub.get("customer"),
            status=sub.get("status", "none"),
            period_end=subscription_period_end_dt(sub),
            plan_id=plan_field,
            stripe_price_id=price_field,
            pending_plan_id=None if clear_pending else _MISSING,
            pending_change_at=None if clear_pending else _MISSING,
        )
        return HttpResponse(status=200)

    return HttpResponse(status=200)
