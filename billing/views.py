# # billing/views.py
# import uuid
# import stripe

# from django.conf import settings
# from rest_framework.permissions import IsAuthenticated
# from rest_framework.response import Response
# from rest_framework.views import APIView

# from .models import BillingProfile
# from .utils import subscription_period_end_dt

# stripe.api_key = settings.STRIPE_SECRET_KEY


# def price_id_for_plan(plan_id: str) -> str | None:
#     cfg = settings.STRIPE_PLANS.get(plan_id)
#     return (cfg or {}).get("price_id")


# def _get_invoice(subscription):
#     inv = subscription.get("latest_invoice")
#     inv_id = None
#     if isinstance(inv, dict):
#         inv_id = inv.get("id")
#     elif isinstance(inv, str):
#         inv_id = inv

#     if not inv_id:
#         return None

#     return stripe.Invoice.retrieve(inv_id, expand=["payment_intent"])


# def _get_client_secret_from_invoice(invoice):
#     if not invoice:
#         return None, None

#     hosted_url = invoice.get("hosted_invoice_url")

#     pi = invoice.get("payment_intent")
#     if not pi:
#         return None, hosted_url

#     if isinstance(pi, str):
#         pi = stripe.PaymentIntent.retrieve(pi)

#     return pi.get("client_secret"), hosted_url


# def _sync_billing_from_stripe(billing: BillingProfile) -> BillingProfile:
#     """
#     Self-heal local BillingProfile by pulling Stripe subscription truth.
#     Uses item-level period end fallback if top-level is missing.
#     """
#     if not billing.stripe_subscription_id:
#         return billing

#     try:
#         sub = stripe.Subscription.retrieve(billing.stripe_subscription_id, expand=["items"])
#     except Exception:
#         return billing

#     status = sub.get("status") or billing.subscription_status
#     period_end = subscription_period_end_dt(sub)
#     customer_id = sub.get("customer") or billing.stripe_customer_id

#     changed = False

#     if status and status != billing.subscription_status:
#         billing.subscription_status = status
#         changed = True

#     if period_end is not None and period_end != billing.current_period_end:
#         billing.current_period_end = period_end
#         changed = True

#     if customer_id and customer_id != billing.stripe_customer_id:
#         billing.stripe_customer_id = customer_id
#         changed = True

#     if changed:
#         billing.save(update_fields=["subscription_status", "current_period_end", "stripe_customer_id", "updated_at"])

#     return billing


# class SubscribeView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         user = request.user
#         profile, _ = BillingProfile.objects.get_or_create(user=user)

#         # Already active (optional sync to prevent drift)
#         if profile.is_active and profile.stripe_subscription_id:
#             profile = _sync_billing_from_stripe(profile)
#             if profile.is_active:
#                 return Response({"detail": "You already have an active subscription."}, status=400)

#         # 1) Create/reuse Stripe Customer
#         if not profile.stripe_customer_id:
#             customer = stripe.Customer.create(
#                 email=getattr(user, "email", None) or None,
#                 metadata={"user_id": str(user.id)},
#             )
#             profile.stripe_customer_id = customer["id"]
#             profile.save(update_fields=["stripe_customer_id", "updated_at"])

#         # 2) Ephemeral Key
#         eph_key = stripe.EphemeralKey.create(
#             customer=profile.stripe_customer_id,
#             stripe_version=settings.STRIPE_API_VERSION,
#         )

#         # 3) If existing incomplete subscription → reuse it
#         if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
#             sub = stripe.Subscription.retrieve(
#                 profile.stripe_subscription_id,
#                 expand=["latest_invoice.payment_intent", "items"],
#             )

#             invoice = _get_invoice(sub)
#             client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

#             if client_secret:
#                 return Response({
#                     "customer_id": profile.stripe_customer_id,
#                     "ephemeral_key_secret": eph_key["secret"],
#                     "payment_intent_client_secret": client_secret,
#                     "subscription_id": sub["id"],
#                 })

#             if hosted_url:
#                 return Response({
#                     "customer_id": profile.stripe_customer_id,
#                     "ephemeral_key_secret": eph_key["secret"],
#                     "subscription_id": sub["id"],
#                     "hosted_invoice_url": hosted_url,
#                     "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment.",
#                 }, status=200)

#             return Response({
#                 "detail": "No payable invoice / PaymentIntent found. Check Stripe → Invoice for this subscription.",
#                 "subscription_id": sub["id"],
#             }, status=400)

#         # 4) Create NEW subscription
#         idempotency_key = (
#             request.headers.get("Idempotency-Key")
#             or request.headers.get("X-Idempotency-Key")
#             or f"subscribe:{user.id}:{uuid.uuid4()}"
#         )

#         sub = stripe.Subscription.create(
#             customer=profile.stripe_customer_id,
#             items=[{"price": settings.STRIPE_PRICE_ID_MONTHLY}],
#             collection_method="charge_automatically",
#             payment_behavior="default_incomplete",
#             payment_settings={"save_default_payment_method": "on_subscription"},
#             expand=["latest_invoice.payment_intent", "items"],
#             metadata={"user_id": str(user.id)},
#             idempotency_key=idempotency_key,
#         )

#         profile.stripe_subscription_id = sub["id"]
#         profile.subscription_status = sub.get("status", "incomplete")

#         # ✅ item-level fallback
#         cpe = subscription_period_end_dt(sub)
#         if cpe is not None:
#             profile.current_period_end = cpe

#         profile.save(update_fields=[
#             "stripe_subscription_id",
#             "subscription_status",
#             "current_period_end",
#             "updated_at",
#         ])

#         invoice = _get_invoice(sub)
#         client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

#         if client_secret:
#             return Response({
#                 "customer_id": profile.stripe_customer_id,
#                 "ephemeral_key_secret": eph_key["secret"],
#                 "payment_intent_client_secret": client_secret,
#                 "subscription_id": sub["id"],
#             })

#         if hosted_url:
#             return Response({
#                 "customer_id": profile.stripe_customer_id,
#                 "ephemeral_key_secret": eph_key["secret"],
#                 "subscription_id": sub["id"],
#                 "hosted_invoice_url": hosted_url,
#                 "detail": "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment.",
#             }, status=200)

#         return Response({
#             "detail": "Stripe did not return PaymentIntent client_secret or hosted invoice url.",
#             "subscription_id": sub["id"],
#         }, status=400)


# class SubscriptionStatusView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         billing = getattr(request.user, "billing", None)
#         if not billing:
#             return Response({"is_active": False, "status": "none", "current_period_end": None})

#         # ✅ Self-heal if missing period end OR if status could be stale
#         if billing.stripe_subscription_id and (billing.current_period_end is None):
#             billing = _sync_billing_from_stripe(billing)

#         return Response({
#             "is_active": billing.is_active,
#             "status": billing.subscription_status,
#             "current_period_end": billing.current_period_end,
#         })


# class CustomerPortalView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         billing = getattr(request.user, "billing", None)
#         if not billing or not billing.stripe_customer_id:
#             return Response({"detail": "No Stripe customer found for this user."}, status=400)

#         session = stripe.billing_portal.Session.create(
#             customer=billing.stripe_customer_id,
#             return_url=settings.BILLING_RETURN_URL,
#         )

#         return Response({"url": session["url"]})


# class CancelSubscriptionView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         billing = getattr(request.user, "billing", None)
#         if not billing or not billing.stripe_subscription_id:
#             return Response({"detail": "No subscription found."}, status=400)

#         # recommended: cancel at period end
#         cancel_at_period_end = bool(request.data.get("cancel_at_period_end", True))

#         sub = stripe.Subscription.modify(
#             billing.stripe_subscription_id,
#             cancel_at_period_end=cancel_at_period_end,
#             expand=["items"],
#         )

#         # update local db (status can remain active until period end)
#         billing.subscription_status = sub.get("status") or billing.subscription_status
#         pe = subscription_period_end_dt(sub)
#         if pe is not None:
#             billing.current_period_end = pe
#         billing.save(update_fields=["subscription_status", "current_period_end", "updated_at"])

#         return Response({
#             "status": sub.get("status"),
#             "cancel_at_period_end": sub.get("cancel_at_period_end"),
#             "current_period_end": billing.current_period_end,
#         })







# billing/views.py
import uuid
from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BillingProfile
from .utils import subscription_period_end_dt

stripe.api_key = settings.STRIPE_SECRET_KEY


def _price_id_for_plan(plan_id: str) -> str | None:
    cfg = getattr(settings, "STRIPE_PLANS", {}).get(plan_id) or {}
    return cfg.get("price_id")


def _extract_subscription_item(sub) -> tuple[str | None, str | None]:
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return None, None
    item = items[0]
    price = item.get("price") or {}
    price_id = price.get("id") if isinstance(price, dict) else None
    return item.get("id"), price_id


def _plan_id_from_price_id(price_id: str | None) -> str | None:
    if not price_id:
        return None
    for plan_id, cfg in getattr(settings, "STRIPE_PLANS", {}).items():
        if cfg.get("price_id") == price_id:
            return plan_id
    return None


def _unit_amount_of_price(price_id: str) -> int | None:
    try:
        p = stripe.Price.retrieve(price_id)
        return p.get("unit_amount")
    except Exception:
        return None


def _unix(dt: datetime) -> int:
    return int(dt.replace(tzinfo=dt_timezone.utc).timestamp())


def _get_invoice(subscription):
    inv = subscription.get("latest_invoice")

    # already expanded
    if isinstance(inv, dict):
        return inv

    # id only, fetch + expand
    if isinstance(inv, str) and inv:
        return stripe.Invoice.retrieve(inv, expand=["payment_intent"])

    return None


def _get_client_secret_from_invoice(invoice):
    if not invoice:
        return None, None

    hosted_url = invoice.get("hosted_invoice_url")

    pi = invoice.get("payment_intent")
    if not pi:
        return None, hosted_url

    if isinstance(pi, str):
        try:
            pi = stripe.PaymentIntent.retrieve(pi)
        except Exception:
            return None, hosted_url

    return pi.get("client_secret"), hosted_url


def _release_schedule_if_any(schedule_id: str | None):
    """
    If you created a SubscriptionSchedule (for downgrade at period end),
    release it before making other subscription changes.
    """
    if not schedule_id:
        return
    try:
        stripe.SubscriptionSchedule.release(schedule_id)
    except Exception:
        # safe ignore (maybe already released/canceled)
        return


def _sync_billing_from_stripe(billing: BillingProfile) -> BillingProfile:
    if not billing.stripe_subscription_id:
        return billing

    try:
        sub = stripe.Subscription.retrieve(billing.stripe_subscription_id, expand=["items"])
    except Exception:
        return billing

    status = sub.get("status") or billing.subscription_status
    period_end = subscription_period_end_dt(sub)
    customer_id = sub.get("customer") or billing.stripe_customer_id

    _, price_id = _extract_subscription_item(sub)
    plan_id = _plan_id_from_price_id(price_id)

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

    if plan_id and plan_id != billing.plan_id:
        billing.plan_id = plan_id
        changed = True

    if price_id and price_id != billing.stripe_price_id:
        billing.stripe_price_id = price_id
        changed = True

    if changed:
        billing.save(update_fields=[
            "subscription_status",
            "current_period_end",
            "stripe_customer_id",
            "plan_id",
            "stripe_price_id",
            "updated_at",
        ])

    return billing


class SubscribeView(APIView):
    """
    POST { "plan_id": "monthly|quarterly|yearly|free" }

    Returns:
      - customer_id
      - ephemeral_key_secret
      - payment_intent_client_secret (when available)
      - subscription_id
      - plan_id
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile, _ = BillingProfile.objects.get_or_create(user=user)

        plan_id = (request.data.get("plan_id") or "monthly").lower().strip()

        # If an old downgrade schedule exists, release it to avoid conflicts
        _release_schedule_if_any(getattr(profile, "stripe_schedule_id", None))
        profile.stripe_schedule_id = None
        profile.pending_plan_id = None
        profile.pending_change_at = None
        profile.save(update_fields=["stripe_schedule_id", "pending_plan_id", "pending_change_at", "updated_at"])

        # Free plan: no Stripe payment
        if plan_id == "free":
            profile.plan_id = "free"
            profile.subscription_status = "none"
            profile.current_period_end = None
            profile.stripe_price_id = None
            profile.save(update_fields=[
                "plan_id", "subscription_status", "current_period_end",
                "stripe_price_id", "updated_at"
            ])
            return Response({"plan_id": "free", "detail": "Free plan selected."})

        price_id = _price_id_for_plan(plan_id)
        if not price_id:
            return Response({"detail": "Invalid plan_id"}, status=400)

        # If already active, block duplicate subscribe
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

        # 2) Ephemeral Key (PaymentSheet customer mode)
        eph_key = stripe.EphemeralKey.create(
            customer=profile.stripe_customer_id,
            stripe_version=settings.STRIPE_API_VERSION,
        )

        # 3) Reuse existing incomplete subscription if present
        if profile.stripe_subscription_id and profile.subscription_status in ("incomplete", "past_due", "unpaid"):
            sub = stripe.Subscription.retrieve(
                profile.stripe_subscription_id,
                expand=["latest_invoice.payment_intent", "items"],
            )

            item_id, current_price_id = _extract_subscription_item(sub)
            if item_id and current_price_id and current_price_id != price_id:
                stripe.Subscription.modify(
                    sub["id"],
                    items=[{"id": item_id, "price": price_id}],
                    proration_behavior="none",
                    expand=["latest_invoice.payment_intent", "items"],
                )
                sub = stripe.Subscription.retrieve(
                    profile.stripe_subscription_id,
                    expand=["latest_invoice.payment_intent", "items"],
                )

            profile.plan_id = plan_id
            profile.stripe_price_id = price_id
            profile.save(update_fields=["plan_id", "stripe_price_id", "updated_at"])

            invoice = _get_invoice(sub)
            client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

            resp = {
                "plan_id": plan_id,
                "customer_id": profile.stripe_customer_id,
                "ephemeral_key_secret": eph_key["secret"],
                "subscription_id": sub["id"],
            }
            if client_secret:
                resp["payment_intent_client_secret"] = client_secret
            if hosted_url and not client_secret:
                resp["hosted_invoice_url"] = hosted_url
                resp["detail"] = "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment."

            return Response(resp, status=200 if (client_secret or hosted_url) else 400)

        # 4) Create NEW subscription
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("X-Idempotency-Key")
            or f"subscribe:{user.id}:{uuid.uuid4()}"
        )

        sub = stripe.Subscription.create(
            customer=profile.stripe_customer_id,
            items=[{"price": price_id}],
            collection_method="charge_automatically",
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent", "items"],
            metadata={"user_id": str(user.id), "plan_id": plan_id},
            idempotency_key=idempotency_key,
        )

        profile.stripe_subscription_id = sub["id"]
        profile.subscription_status = sub.get("status", "incomplete")
        profile.plan_id = plan_id
        profile.stripe_price_id = price_id

        cpe = subscription_period_end_dt(sub)
        if cpe is not None:
            profile.current_period_end = cpe

        profile.save(update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "plan_id",
            "stripe_price_id",
            "current_period_end",
            "updated_at",
        ])

        invoice = _get_invoice(sub)
        client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

        resp = {
            "plan_id": plan_id,
            "customer_id": profile.stripe_customer_id,
            "ephemeral_key_secret": eph_key["secret"],
            "subscription_id": sub["id"],
        }
        if client_secret:
            resp["payment_intent_client_secret"] = client_secret
        if hosted_url and not client_secret:
            resp["hosted_invoice_url"] = hosted_url
            resp["detail"] = "No PaymentIntent client_secret found. Use hosted_invoice_url (open in WebView) to complete payment."

        return Response(resp, status=200 if (client_secret or hosted_url) else 400)


class SubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing:
            return Response({
                "is_active": False,
                "status": "none",
                "current_period_end": None,
                "plan_id": "free",
                "pending_plan_id": None,
                "pending_change_at": None,
            })

        if billing.stripe_subscription_id and (billing.current_period_end is None or not billing.plan_id):
            billing = _sync_billing_from_stripe(billing)

        return Response({
            "is_active": billing.is_active,
            "status": billing.subscription_status,
            "current_period_end": billing.current_period_end,
            "plan_id": billing.plan_id,
            "pending_plan_id": billing.pending_plan_id,
            "pending_change_at": billing.pending_change_at,
        })


class ChangePlanView(APIView):
    """
    POST { "plan_id": "monthly|quarterly|yearly" }

    Policy:
      - Upgrade (more expensive): charge immediately
      - Downgrade (cheaper): schedule at period end
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_subscription_id:
            return Response({"detail": "No subscription found."}, status=400)

        new_plan = (request.data.get("plan_id") or "").lower().strip()
        if new_plan not in ("monthly", "quarterly", "yearly"):
            return Response({"detail": "Invalid plan_id"}, status=400)

        new_price_id = _price_id_for_plan(new_plan)
        if not new_price_id:
            return Response({"detail": "Plan not configured."}, status=400)

        # If a previous schedule exists (old downgrade), release it first
        _release_schedule_if_any(getattr(billing, "stripe_schedule_id", None))
        billing.stripe_schedule_id = None
        billing.pending_plan_id = None
        billing.pending_change_at = None
        billing.save(update_fields=["stripe_schedule_id", "pending_plan_id", "pending_change_at", "updated_at"])

        sub = stripe.Subscription.retrieve(
            billing.stripe_subscription_id,
            expand=["items", "latest_invoice.payment_intent"],
        )

        item_id, current_price_id = _extract_subscription_item(sub)
        if not item_id or not current_price_id:
            return Response({"detail": "Subscription has no items."}, status=400)

        if current_price_id == new_price_id:
            return Response({"detail": "Already on this plan.", "plan_id": new_plan})

        current_amt = _unit_amount_of_price(current_price_id)
        new_amt = _unit_amount_of_price(new_price_id)
        if current_amt is None or new_amt is None:
            return Response({"detail": "Could not compare prices."}, status=400)

        is_upgrade = new_amt > current_amt
        period_end = subscription_period_end_dt(sub)

        # -----------------------
        # UPGRADE: apply now
        # -----------------------
        if is_upgrade:
            # IMPORTANT: In pending updates mode you can't pass cancel_at_period_end in same call.
            # So clear it in a separate call first (if needed).
            if sub.get("cancel_at_period_end"):
                stripe.Subscription.modify(sub["id"], cancel_at_period_end=False)

            updated = stripe.Subscription.modify(
                sub["id"],
                items=[{"id": item_id, "price": new_price_id}],
                proration_behavior="always_invoice",
                payment_behavior="pending_if_incomplete",
                expand=["latest_invoice.payment_intent", "items"],
            )

            invoice = _get_invoice(updated)
            client_secret, hosted_url = _get_client_secret_from_invoice(invoice)

            # Mark as pending locally; webhooks will set the real plan after payment succeeds
            billing.pending_plan_id = new_plan
            billing.pending_change_at = timezone.now()
            billing.save(update_fields=["pending_plan_id", "pending_change_at", "updated_at"])

            resp = {
                "mode": "upgrade_now",
                "requested_plan_id": new_plan,
                "requires_payment": bool(client_secret),
                "stripe_subscription_id": updated.get("id"),
                "status": updated.get("status"),
            }
            if client_secret:
                resp["payment_intent_client_secret"] = client_secret
            if hosted_url and not client_secret:
                resp["hosted_invoice_url"] = hosted_url

            return Response(resp)

        # -----------------------
        # DOWNGRADE: schedule at period end
        # -----------------------
        if not period_end:
            return Response({"detail": "Missing current_period_end. Wait for webhook/status sync."}, status=400)

        # Create schedule from existing subscription
        schedule = stripe.SubscriptionSchedule.create(from_subscription=sub["id"])

        schedule = stripe.SubscriptionSchedule.modify(
            schedule["id"],
            end_behavior="release",
            phases=[
                {
                    "start_date": "now",
                    "end_date": _unix(period_end),
                    "items": [{"price": current_price_id, "quantity": 1}],
                    "proration_behavior": "none",
                },
                {
                    "start_date": _unix(period_end),
                    "items": [{"price": new_price_id, "quantity": 1}],
                    "proration_behavior": "none",
                },
            ],
            proration_behavior="none",
        )

        billing.pending_plan_id = new_plan
        billing.pending_change_at = period_end
        billing.stripe_schedule_id = schedule.get("id")
        billing.save(update_fields=["pending_plan_id", "pending_change_at", "stripe_schedule_id", "updated_at"])

        return Response({
            "mode": "downgrade_at_period_end",
            "pending_plan_id": new_plan,
            "pending_change_at": billing.pending_change_at,
            "subscription_schedule_id": billing.stripe_schedule_id,
            "current_period_end": billing.current_period_end,
        })


class CustomerPortalView(APIView):
    """
    POST -> returns { url } to open Stripe Customer Portal in a WebView.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_customer_id:
            return Response({"detail": "No Stripe customer found for this user."}, status=400)

        kwargs = {
            "customer": billing.stripe_customer_id,
            "return_url": settings.BILLING_RETURN_URL,
        }

        cfg_id = getattr(settings, "STRIPE_PORTAL_CONFIG_ID", None)
        if cfg_id:
            kwargs["configuration"] = cfg_id

        session = stripe.billing_portal.Session.create(**kwargs)
        return Response({"url": session["url"]})


class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_subscription_id:
            return Response({"detail": "No subscription found."}, status=400)

        cancel_at_period_end = bool(request.data.get("cancel_at_period_end", True))

        # Fetch current subscription state
        sub = stripe.Subscription.retrieve(
            billing.stripe_subscription_id,
            expand=["items"],
        )

        # ✅ If already canceled, do not modify
        if sub.get("status") == "canceled":
            # Update local DB (self-heal)
            billing.subscription_status = "canceled"
            billing.current_period_end = subscription_period_end_dt(sub) or billing.current_period_end
            billing.save(update_fields=["subscription_status", "current_period_end", "updated_at"])

            return Response({
                "detail": "Subscription is already canceled.",
                "status": "canceled",
                "cancel_at_period_end": sub.get("cancel_at_period_end"),
                "current_period_end": billing.current_period_end,
            }, status=200)

        # Otherwise we can update cancellation settings
        sub = stripe.Subscription.modify(
            billing.stripe_subscription_id,
            cancel_at_period_end=cancel_at_period_end,
            expand=["items"],
        )

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



class ResumeSubscriptionView(APIView):
    """
    POST -> undo cancel_at_period_end
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing = getattr(request.user, "billing", None)
        if not billing or not billing.stripe_subscription_id:
            return Response({"detail": "No subscription found."}, status=400)

        sub = stripe.Subscription.modify(
            billing.stripe_subscription_id,
            cancel_at_period_end=False,
            expand=["items"],
        )

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
