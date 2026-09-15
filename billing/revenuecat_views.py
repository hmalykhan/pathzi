"""
The RevenueCat webhook, and the refresh call the app makes after buying.

    POST /api/billing/revenuecat/webhook/   RevenueCat tells us what happened
    POST /api/billing/refresh/              the app asks us to check now

The webhook is a plain Django view, not DRF, for one specific reason: the
signature is computed over the raw request bytes, and a DRF parser would
read and re-encode the body before we ever saw it.
"""
import json
import logging

from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserProfile
from billing.models import BillingProfile, RevenueCatEvent
from billing.services import revenuecat as rc
from billing.services.access import access_for

logger = logging.getLogger(__name__)


def _profile_for_app_user_id(app_user_id, aliases=None):
    """
    Find the Pathzi account behind a RevenueCat customer.

    The app signs into RevenueCat as UserProfile.account_uuid. Aliases are
    checked too, because a purchase made before login starts anonymous and
    is later merged.
    """
    candidates = [app_user_id] + list(aliases or [])
    for value in candidates:
        if not value:
            continue
        try:
            profile = UserProfile.objects.filter(account_uuid=value).first()
        except (ValueError, TypeError):
            continue          # not a uuid - an anonymous RevenueCat id
        if profile is not None:
            return profile
    return None


def _apply_to_billing(user, *, plan_id, expires_at, store, product_id,
                      auto_renewing, customer_id):
    """
    Write what we now believe to the BillingProfile.

    The access rule lives here and nowhere else: paid access lasts while
    the expiry is in the future, whatever the event was called.
    """
    billing, _ = BillingProfile.objects.get_or_create(user=user)

    has_access = bool(expires_at and expires_at > timezone.now())

    billing.subscription_status = "active" if has_access else "canceled"
    if expires_at is not None:
        billing.current_period_end = expires_at
    if plan_id:
        billing.plan_id = plan_id
    if store:
        billing.store = store
    if product_id:
        billing.store_product_id = product_id
    if auto_renewing is not None:
        billing.auto_renewing = auto_renewing
    if customer_id:
        billing.revenuecat_customer_id = str(customer_id)

    billing.save()
    return billing


@csrf_exempt
@require_POST
def revenuecat_webhook(request):
    """
    RevenueCat calls this whenever a subscription changes.

    Answers 200 to anything genuine, even when we cannot match it to an
    account - a 500 would make RevenueCat retry the same delivery for days.
    Only a failed security check answers 401.
    """
    raw = request.body

    if not rc.check_authorization(request.META.get("HTTP_AUTHORIZATION", "")):
        logger.warning("RevenueCat webhook rejected: bad Authorization header")
        return HttpResponse(status=401)

    signature = request.META.get("HTTP_X_REVENUECAT_WEBHOOK_SIGNATURE", "")
    if not rc.check_signature(raw, signature):
        return HttpResponse(status=401)

    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("RevenueCat webhook: body was not JSON")
        return HttpResponse(status=400)

    event = body.get("event") or {}
    event_id = event.get("id")
    event_type = (event.get("type") or "").upper()

    if not event_id:
        logger.warning("RevenueCat webhook: event had no id")
        return HttpResponse(status=400)

    app_user_id = event.get("app_user_id")

    # Already handled? RevenueCat retries until we answer 200.
    try:
        record, created = RevenueCatEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type[:64],
                "app_user_id": (str(app_user_id) if app_user_id else None),
                "payload": body,
            },
        )
    except IntegrityError:
        return HttpResponse(status=200)

    if not created:
        return HttpResponse(status=200)

    profile = _profile_for_app_user_id(app_user_id, event.get("aliases"))
    if profile is None:
        # Keep the event: this is how a purchase that cannot find its owner
        # is discovered, instead of vanishing.
        record.note = "no account matched app_user_id=%s" % (app_user_id,)[:200]
        record.save(update_fields=["note"])
        logger.error(
            "RevenueCat %s: no Pathzi account for app_user_id=%s. The app may "
            "not be logging into RevenueCat with account_uuid.",
            event_type, app_user_id,
        )
        return HttpResponse(status=200)

    product_id = event.get("product_id")
    expires_at = rc.ms_to_dt(event.get("expiration_at_ms"))
    store = rc.store_from_event(event.get("store"))
    plan_id = rc.plan_from_product(product_id)

    # CANCELLATION only means auto-renew is off; the expiry has not moved.
    auto_renewing = None
    if event_type in ("CANCELLATION", "EXPIRATION"):
        auto_renewing = False
    elif event_type in ("INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION",
                        "PRODUCT_CHANGE", "SUBSCRIPTION_EXTENDED"):
        auto_renewing = True

    with transaction.atomic():
        _apply_to_billing(
            profile.appuser,
            plan_id=plan_id,
            expires_at=expires_at,
            store=store,
            product_id=product_id,
            auto_renewing=auto_renewing,
            customer_id=app_user_id,
        )
        record.handled = True
        record.note = "%s -> plan=%s expires=%s" % (event_type, plan_id, expires_at)
        record.save(update_fields=["handled", "note"])

    logger.info(
        "RevenueCat %s applied: user=%s plan=%s expires=%s",
        event_type, profile.appuser_id, plan_id, expires_at,
    )
    return HttpResponse(status=200)


class BillingRefreshView(APIView):
    """
    POST /api/billing/refresh/

    Called by the app straight after a purchase, while our webhook may still
    be in flight. Asks RevenueCat directly and returns the same access object
    as the status endpoint.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = UserProfile.objects.filter(appuser=request.user).first()
        account_uuid = str(profile.account_uuid) if profile and profile.account_uuid else None

        state = rc.fetch_customer_state(account_uuid)

        if state is None:
            # RevenueCat unreachable. Say so rather than removing access.
            return Response(
                {
                    "status": True,
                    "message": "Could not reach the store just now. Your access is unchanged.",
                    "data": {"refreshed": False, "access": access_for(request.user)},
                },
                status=200,
            )

        if state.get("found") and state.get("expires_at"):
            _apply_to_billing(
                request.user,
                plan_id=state.get("plan_id"),
                expires_at=state.get("expires_at"),
                store=state.get("store"),
                product_id=state.get("product_id"),
                auto_renewing=state.get("auto_renewing"),
                customer_id=account_uuid,
            )

        return Response(
            {
                "status": True,
                "message": "Access refreshed.",
                "data": {"refreshed": True, "access": access_for(request.user)},
            },
            status=200,
        )
