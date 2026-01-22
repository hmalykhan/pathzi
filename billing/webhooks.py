# # billing/webhooks.py
# import json
# import stripe

# from django.conf import settings
# from django.http import HttpResponse
# from django.utils import timezone
# from django.views.decorators.csrf import csrf_exempt

# from .models import BillingProfile, StripeEvent
# from .utils import subscription_period_end_dt

# stripe.api_key = settings.STRIPE_SECRET_KEY


# def _json_safe(obj):
#     try:
#         return json.loads(json.dumps(obj, default=str))
#     except Exception:
#         return {"raw": str(obj)}


# def _update_billing(*, sub_id=None, customer_id=None, status=None, period_end=None):
#     """
#     Update BillingProfile without ever overwriting current_period_end with None.
#     """
#     qs = BillingProfile.objects.none()

#     if sub_id:
#         qs = BillingProfile.objects.filter(stripe_subscription_id=sub_id)

#     if (not qs.exists()) and customer_id:
#         qs = BillingProfile.objects.filter(stripe_customer_id=customer_id)

#     if not qs.exists():
#         return

#     update_fields = {"updated_at": timezone.now()}

#     if sub_id:
#         update_fields["stripe_subscription_id"] = sub_id

#     if status is not None:
#         update_fields["subscription_status"] = status

#     # ✅ only write if we actually have a value
#     if period_end is not None:
#         update_fields["current_period_end"] = period_end

#     qs.update(**update_fields)


# def _retrieve_subscription(sub_id: str):
#     try:
#         # items are included by default, but we keep it explicit
#         return stripe.Subscription.retrieve(sub_id, expand=["items"])
#     except Exception:
#         return None


# @csrf_exempt
# def stripe_webhook(request):
#     payload = request.body
#     sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

#     try:
#         event = stripe.Webhook.construct_event(
#             payload,
#             sig_header,
#             settings.STRIPE_WEBHOOK_SECRET,
#         )
#     except (ValueError, stripe.error.SignatureVerificationError):
#         return HttpResponse(status=400)

#     # De-dupe (race-safe)
#     _, created = StripeEvent.objects.get_or_create(
#         event_id=event["id"],
#         defaults={
#             "event_type": event["type"],
#             "payload": _json_safe(event),
#         },
#     )
#     if not created:
#         return HttpResponse(status=200)

#     event_type = event["type"]
#     obj = event["data"]["object"]

#     # ---- Subscription state sync ----
#     if event_type.startswith("customer.subscription."):
#         sub_id = obj.get("id")
#         customer_id = obj.get("customer")
#         status = obj.get("status") or "none"

#         # ✅ Works for both legacy and item-level period end
#         period_end = subscription_period_end_dt(obj)

#         # ✅ If Stripe didn't include items in this event payload, fetch subscription once
#         if period_end is None and sub_id:
#             sub = _retrieve_subscription(sub_id)
#             if sub:
#                 period_end = subscription_period_end_dt(sub)
#                 customer_id = customer_id or sub.get("customer")
#                 status = sub.get("status") or status

#         _update_billing(
#             sub_id=sub_id,
#             customer_id=customer_id,
#             status=status,
#             period_end=period_end,
#         )

#         return HttpResponse(status=200)

#     # ---- Payment outcomes ----
#     if event_type in ("invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"):
#         sub_id = obj.get("subscription")
#         if not sub_id:
#             return HttpResponse(status=200)

#         sub = _retrieve_subscription(sub_id)
#         if not sub:
#             return HttpResponse(status=200)

#         _update_billing(
#             sub_id=sub_id,
#             customer_id=sub.get("customer"),
#             status=sub.get("status", "none"),
#             period_end=subscription_period_end_dt(sub),
#         )
#         return HttpResponse(status=200)

#     return HttpResponse(status=200)






import json
import stripe

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import BillingProfile, StripeEvent
from .utils import subscription_period_end_dt, ts_to_dt

stripe.api_key = settings.STRIPE_SECRET_KEY
_MISSING = object()


def _json_safe(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


def _subscription_price_id(sub_obj):
    items = (sub_obj.get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    return price.get("id") if isinstance(price, dict) else None


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

    # Optional: if you use schedules for downgrades, track pending changes
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
                price = items[0].get("price") or {}
                price_id = price.get("id") if isinstance(price, dict) else None
                pending_plan = _plan_id_from_price_id(price_id)
            pending_at = ts_to_dt(next_phase.get("start_date"))

        if sub_id:
            _update_billing(
                sub_id=sub_id,
                stripe_schedule_id=sched.get("id"),
                pending_plan_id=pending_plan,
                pending_change_at=pending_at,
            )

        if event_type == "subscription_schedule.released" and sub_id:
            _update_billing(
                sub_id=sub_id,
                pending_plan_id=None,
                pending_change_at=None,
                stripe_schedule_id=None,
            )

        return HttpResponse(status=200)

    # Subscription state sync
    if event_type.startswith("customer.subscription."):
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        status = obj.get("status") or "none"

        period_end = subscription_period_end_dt(obj)
        price_id = _subscription_price_id(obj)
        plan_id = _plan_id_from_price_id(price_id)

        # If items/period_end missing in event payload, fetch the subscription once
        if (period_end is None or price_id is None) and sub_id:
            sub = _retrieve_subscription(sub_id)
            if sub:
                period_end = period_end or subscription_period_end_dt(sub)
                customer_id = customer_id or sub.get("customer")
                status = sub.get("status") or status
                price_id = price_id or _subscription_price_id(sub)
                plan_id = plan_id or _plan_id_from_price_id(price_id)

        # If subscription actually changed now, clear pending info
        _update_billing(
            sub_id=sub_id,
            customer_id=customer_id,
            status=status,
            period_end=period_end,
            plan_id=plan_id if plan_id is not None else _MISSING,
            stripe_price_id=price_id if price_id is not None else _MISSING,
            pending_plan_id=None,
            pending_change_at=None,
            stripe_schedule_id=None,
        )
        return HttpResponse(status=200)

    # Invoice events (payment success/fail/action required)
    if event_type in ("invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = obj.get("subscription")
        if not sub_id:
            return HttpResponse(status=200)

        sub = _retrieve_subscription(sub_id)
        if not sub:
            return HttpResponse(status=200)

        price_id = _subscription_price_id(sub)
        plan_id = _plan_id_from_price_id(price_id)

        _update_billing(
            sub_id=sub_id,
            customer_id=sub.get("customer"),
            status=sub.get("status", "none"),
            period_end=subscription_period_end_dt(sub),
            plan_id=plan_id if plan_id is not None else _MISSING,
            stripe_price_id=price_id if price_id is not None else _MISSING,
        )
        return HttpResponse(status=200)

    return HttpResponse(status=200)

