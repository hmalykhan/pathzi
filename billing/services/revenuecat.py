"""
RevenueCat: proving a webhook is genuine, and turning it into access.

Apple and Google take the money; RevenueCat tells us what happened. This
module is the only place that trusts anything RevenueCat says, so the
checks live here and nowhere else.

The access rule is deliberately one line: a user has paid access while
`expiration_at_ms` is in the future. That single rule gives the correct
behaviour for every event type -

  CANCELLATION   auto-renew is off, but the expiry has not moved, so the
                 user keeps what they paid for. Revoking here would cut
                 off a paying customer the moment they cancel.
  BILLING_ISSUE  the store is retrying the payment and usually extends the
                 expiry as a grace period. Access continues.
  EXPIRATION     the expiry is now in the past. This - and only this -
                 is what removes access.

See PART2_PAYMENTS.md section 5.
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_ROOT = "https://api.revenuecat.com/v2"
SIGNATURE_HEADER = "X-RevenueCat-Webhook-Signature"
SIGNATURE_TOLERANCE_SECONDS = 300      # reject replays of an old delivery
API_TIMEOUT_SECONDS = 20

# RevenueCat's store names -> ours.
STORE_MAP = {
    "APP_STORE": "apple",
    "MAC_APP_STORE": "apple",
    "PLAY_STORE": "google",
    "AMAZON": "amazon",
    "STRIPE": "stripe",
    "PROMOTIONAL": "promotional",
    "TEST_STORE": "test",
    "RC_BILLING": "web",
    "PADDLE": "paddle",
}

# Where the user manages or cancels their subscription. Apple and Google
# require us to send them to the store's own screen, not a page of ours.
MANAGE_URLS = {
    "apple": "https://apps.apple.com/account/subscriptions",
    "google": "https://play.google.com/store/account/subscriptions",
}


def ms_to_dt(ms):
    """RevenueCat sends milliseconds; Stripe sent seconds. Hence a second helper."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Is this delivery genuine?
# --------------------------------------------------------------------------

def check_authorization(header_value):
    """
    The shared password we gave RevenueCat. Compared in constant time.

    An optional "Bearer " prefix is accepted. RevenueCat's Authorization
    field is free text, so whoever fills it in may or may not type the
    prefix; rejecting one of the two spellings produced a 401 that looked
    exactly like a wrong secret and cost an afternoon to find. Only the
    prefix is optional - the value itself must still match exactly.
    """
    expected = settings.REVENUECAT_WEBHOOK_SECRET
    if not expected:
        logger.error("REVENUECAT_WEBHOOK_SECRET is not set - refusing every webhook")
        return False

    provided = (header_value or "").strip()
    if provided[:7].lower() == "bearer ":
        provided = provided[7:].strip()

    return hmac.compare_digest(provided, expected)


def check_signature(raw_body, header_value, now=None):
    """
    Verify X-RevenueCat-Webhook-Signature: `t=<unix>,v1=<hmac sha256 hex>`.

    The signed payload is "<timestamp>." followed by the raw body bytes
    exactly as they arrived - parsing the JSON first and re-encoding it
    would change the bytes and every signature would fail.
    """
    secret = settings.REVENUECAT_SIGNING_SECRET
    if not secret:
        # Signing not configured: the Authorization header is the only check.
        logger.warning("REVENUECAT_SIGNING_SECRET is not set - skipping signature check")
        return True

    if not header_value:
        logger.warning("Webhook rejected: signature header missing")
        return False

    try:
        parts = dict(p.split("=", 1) for p in header_value.split(","))
        timestamp = parts["t"]
        provided = parts["v1"]
    except (ValueError, KeyError):
        logger.warning("Webhook rejected: signature header malformed")
        return False

    signed = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, provided):
        logger.warning("Webhook rejected: signature does not match")
        return False

    now = now if now is not None else time.time()
    try:
        age = abs(now - int(timestamp))
    except (TypeError, ValueError):
        logger.warning("Webhook rejected: signature timestamp unreadable")
        return False

    if age > SIGNATURE_TOLERANCE_SECONDS:
        logger.warning("Webhook rejected: signature is %.0fs old (replay?)", age)
        return False

    return True


# --------------------------------------------------------------------------
# What did they buy?
# --------------------------------------------------------------------------

def plan_from_product(product_id):
    """
    Work out our plan name from the store's product identifier.

    Matched on substrings so it survives the store naming the product
    "pathzi_monthly", "monthly", or "com.pathzi.sub.monthly".
    Returns None when we do not recognise it - the caller must not guess.
    """
    if not product_id:
        return None

    name = str(product_id).lower()
    if "month" in name:
        return "monthly"
    if "year" in name or "annual" in name:
        return "yearly"
    if "quarter" in name:
        return "quarterly"
    if "life" in name:
        # Deliberately unsupported: BillingProfile has no lifetime plan, and
        # is_active only accepts monthly/quarterly/yearly. Granting access
        # here would need a data-model decision, so we refuse loudly rather
        # than silently sell something we cannot honour.
        logger.error(
            "RevenueCat sent a LIFETIME product (%s) - no such plan exists in "
            "BillingProfile, so no access was granted. This needs a decision.",
            product_id,
        )
        return None

    logger.error("Unrecognised RevenueCat product id: %s", product_id)
    return None


def store_from_event(store):
    return STORE_MAP.get((store or "").upper(), (store or "").lower() or None)


def manage_url_for(store):
    return MANAGE_URLS.get(store)


# --------------------------------------------------------------------------
# Asking RevenueCat directly (used by the refresh endpoint)
# --------------------------------------------------------------------------

def _api_get(path):
    key = settings.REVENUECAT_SECRET_KEY
    project = settings.REVENUECAT_PROJECT_ID
    if not key or not project:
        logger.error("RevenueCat API not configured (key or project id missing)")
        return None

    url = "%s/projects/%s/%s" % (API_ROOT, project, path)
    try:
        r = requests.get(
            url,
            headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
            timeout=API_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning("RevenueCat API call failed (%s): %s", path, e)
        return None

    if r.status_code == 404:
        return {"_not_found": True}
    if r.status_code != 200:
        logger.warning("RevenueCat API %s returned %s: %s", path, r.status_code, r.text[:200])
        return None

    try:
        return r.json()
    except ValueError:
        logger.warning("RevenueCat API %s returned unreadable JSON", path)
        return None


def fetch_customer_state(app_user_id):
    """
    Ask RevenueCat what this customer currently owns.

    Used right after a purchase, when the app has paid but our webhook has
    not landed yet, and to repair anything a missed webhook left behind.

    Returns None when RevenueCat could not be reached - the caller must
    leave what it already has rather than wrongly removing access.
    """
    if not app_user_id:
        return None

    subs = _api_get("customers/%s/subscriptions" % app_user_id)
    if subs is None:
        return None
    if subs.get("_not_found"):
        # RevenueCat has never heard of them: they have not bought anything.
        return {"found": False, "active": False, "plan_id": None, "expires_at": None,
                "store": None, "product_id": None, "auto_renewing": None}

    items = subs.get("items", [])

    # The v2 subscription object's exact field names could not be confirmed
    # from the documentation, and this project has had no customer to read a
    # real response from. So: accept the plausible spellings, and log the
    # real keys the first time one arrives. The first true purchase settles
    # it - far better than quietly reading None and removing someone's access.
    if items:
        logger.info("RevenueCat subscription payload keys: %s", sorted(items[0].keys()))

    best = None
    for item in items:
        expires = ms_to_dt(
            item.get("current_period_ends_at")
            or item.get("expires_at")
            or item.get("current_period_end")
            or item.get("expiration_at_ms")
        )
        if expires is None:
            logger.warning(
                "RevenueCat subscription had no readable expiry; keys were %s",
                sorted(item.keys()),
            )
            continue
        if best is None or expires > best[0]:
            best = (expires, item)

    if best is None:
        return {"found": True, "active": False, "plan_id": None, "expires_at": None,
                "store": None, "product_id": None, "auto_renewing": None}

    expires, item = best
    product_id = (item.get("product_id") or item.get("store_identifier")
                  or item.get("product_identifier"))
    status = (item.get("status") or "").lower()

    # "will_renew" is the documented value; the others are defensive.
    auto_renew_raw = item.get("auto_renewal_status", item.get("auto_renew_status"))
    auto_renewing = auto_renew_raw in ("will_renew", "will_renew_at_period_end", True)

    return {
        "found": True,
        "active": expires > datetime.now(dt_timezone.utc),
        "plan_id": plan_from_product(product_id),
        "expires_at": expires,
        "store": store_from_event(item.get("store")),
        "product_id": product_id,
        "auto_renewing": auto_renewing,
        "status": status,
    }
