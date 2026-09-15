"""
Phase 2 tests: is a webhook genuine, and does it grant the right access?

Runs inside one transaction that is rolled back, so the backup database is
left exactly as found.
"""
import os, sys, json, uuid, time, hmac, hashlib, logging
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from django.conf import settings
from django.db import transaction
from django.test import override_settings, Client
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import UserProfile
from billing.models import BillingProfile, RevenueCatEvent
from billing.services import revenuecat as rc
from billing.services.access import access_for, ensure_account_identity
import billing.revenuecat_views as rcv

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

WEBHOOK_URL = "/api/billing/revenuecat/webhook/"


def mk_user(tag):
    e = f"ut_rc_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)
    return u, p


def signed_post(client, body_dict, *, auth=None, secret=None, ts=None, tamper=False):
    raw = json.dumps(body_dict).encode()
    ts = ts if ts is not None else int(time.time())
    secret = secret if secret is not None else settings.REVENUECAT_SIGNING_SECRET
    sig = hmac.new(secret.encode(), str(ts).encode() + b"." + raw, hashlib.sha256).hexdigest()
    if tamper:
        raw = raw.replace(b'"RENEWAL"', b'"INITIAL_PURCHASE"') or raw + b" "
    return client.post(
        WEBHOOK_URL, data=raw, content_type="application/json",
        HTTP_AUTHORIZATION=(settings.REVENUECAT_WEBHOOK_SECRET if auth is None else auth),
        HTTP_X_REVENUECAT_WEBHOOK_SIGNATURE=f"t={ts},v1={sig}",
    )


def event(app_user_id, etype="INITIAL_PURCHASE", product="monthly", days=30, eid=None):
    expires = int((timezone.now() + timedelta(days=days)).timestamp() * 1000)
    return {"api_version": "1.0", "event": {
        "id": eid or ("evt_" + uuid.uuid4().hex[:16]),
        "type": etype, "app_user_id": str(app_user_id), "product_id": product,
        "expiration_at_ms": expires, "purchased_at_ms": int(timezone.now().timestamp()*1000),
        "store": "APP_STORE", "environment": "SANDBOX", "period_type": "NORMAL",
        "entitlement_ids": ["pathzi_pro"],
    }}


def run():
    c = Client()

    print("--- security: only genuine deliveries are accepted ---")
    u, p = mk_user("sec")
    r = signed_post(c, event(p.account_uuid))
    check("a correctly signed webhook is accepted", r.status_code == 200, f"got {r.status_code}")

    r = c.post(WEBHOOK_URL, data=json.dumps(event(p.account_uuid)), content_type="application/json")
    check("no Authorization header is refused", r.status_code == 401, f"got {r.status_code}")

    r = signed_post(c, event(p.account_uuid), auth="wrong-password")
    check("a wrong Authorization header is refused", r.status_code == 401, f"got {r.status_code}")

    r = signed_post(c, event(p.account_uuid), secret="not-the-signing-secret")
    check("a wrong signature is refused", r.status_code == 401, f"got {r.status_code}")

    r = signed_post(c, event(p.account_uuid), ts=int(time.time()) - 900)
    check("an old delivery is refused (replay protection)", r.status_code == 401, f"got {r.status_code}")

    raw = json.dumps(event(p.account_uuid)).encode()
    ts = int(time.time())
    sig = hmac.new(settings.REVENUECAT_SIGNING_SECRET.encode(), str(ts).encode()+b"."+raw, hashlib.sha256).hexdigest()
    r = c.post(WEBHOOK_URL, data=raw + b" ", content_type="application/json",
               HTTP_AUTHORIZATION=settings.REVENUECAT_WEBHOOK_SECRET,
               HTTP_X_REVENUECAT_WEBHOOK_SIGNATURE=f"t={ts},v1={sig}")
    check("a tampered body is refused", r.status_code == 401, f"got {r.status_code}")

    print("\n--- a purchase grants access ---")
    u2, p2 = mk_user("buy")
    before = access_for(u2)
    check("before buying, access comes from the trial", before["source"] == "trial")

    r = signed_post(c, event(p2.account_uuid, "INITIAL_PURCHASE", "monthly", 30))
    check("purchase webhook accepted", r.status_code == 200)
    u2 = User.objects.get(pk=u2.pk)
    acc = access_for(u2)
    check("access now comes from the subscription", acc["source"] == "subscription", acc["source"])
    check("plan is monthly", acc["plan"] == "monthly", str(acc["plan"]))
    check("store is apple", acc["store"] == "apple", str(acc["store"]))
    check("manage_url points at Apple's screen",
          acc["manage_url"] == "https://apps.apple.com/account/subscriptions")
    check("auto_renewing is true", acc["auto_renewing"] is True)
    b = BillingProfile.objects.get(user=u2)
    check("purchase linked to the right account", str(b.revenuecat_customer_id) == str(p2.account_uuid))

    print("\n--- the same delivery twice changes nothing ---")
    ev = event(p2.account_uuid, "RENEWAL", "monthly", 60)
    r1 = signed_post(c, ev)
    end1 = BillingProfile.objects.get(user=u2).current_period_end
    r2 = signed_post(c, ev)          # RevenueCat retrying the same event id
    end2 = BillingProfile.objects.get(user=u2).current_period_end
    check("a retried delivery is accepted", r1.status_code == 200 and r2.status_code == 200)
    check("but it is only applied once", end1 == end2)
    check("only one event row stored", RevenueCatEvent.objects.filter(event_id=ev["event"]["id"]).count() == 1)

    print("\n--- cancelling keeps access until the paid date ---")
    r = signed_post(c, event(p2.account_uuid, "CANCELLATION", "monthly", 60))
    u2 = User.objects.get(pk=u2.pk)
    acc = access_for(u2)
    check("a cancelled user KEEPS access until expiry", acc["has_access"] is True, acc["source"])
    check("but auto_renewing is now false", acc["auto_renewing"] is False)

    print("\n--- only expiry removes access ---")
    r = signed_post(c, event(p2.account_uuid, "EXPIRATION", "monthly", -1))
    u2 = User.objects.get(pk=u2.pk)
    acc = access_for(u2)
    check("after expiry the subscription no longer grants access",
          acc["source"] != "subscription", acc["source"])

    print("\n--- billing issue must not cut anyone off ---")
    u3, p3 = mk_user("grace")
    signed_post(c, event(p3.account_uuid, "INITIAL_PURCHASE", "yearly", 300))
    signed_post(c, event(p3.account_uuid, "BILLING_ISSUE", "yearly", 5))
    u3 = User.objects.get(pk=u3.pk)
    acc = access_for(u3)
    check("a billing issue during grace keeps access", acc["has_access"] is True, acc["source"])

    print("\n--- awkward cases ---")
    r = signed_post(c, event(uuid.uuid4(), "INITIAL_PURCHASE", "monthly", 30))
    check("an unknown app_user_id still answers 200 (no infinite retries)", r.status_code == 200)
    unmatched = RevenueCatEvent.objects.filter(handled=False).exclude(note=None).count()
    check("the unmatched purchase is recorded for investigation", unmatched >= 1)

    u4, p4 = mk_user("life")
    r = signed_post(c, event(p4.account_uuid, "INITIAL_PURCHASE", "lifetime", 3650))
    u4 = User.objects.get(pk=u4.pk)
    check("a lifetime purchase is accepted without crashing", r.status_code == 200)
    check("but grants no subscription, because we have no lifetime plan",
          access_for(u4)["source"] != "subscription")

    check("plan_from_product: monthly", rc.plan_from_product("com.pathzi.sub.monthly") == "monthly")
    check("plan_from_product: yearly", rc.plan_from_product("pathzi_annual") == "yearly")
    check("plan_from_product: unknown is refused", rc.plan_from_product("mystery_box") is None)

    print("\n--- nothing that worked before has changed ---")
    u5, p5 = mk_user("old")
    f = APIRequestFactory()
    from billing.views import SubscriptionStatusView
    req = f.get("/api/billing/status/"); force_authenticate(req, user=u5)
    data = SubscriptionStatusView.as_view()(req).data
    for k in ("is_active", "status", "current_period_end", "plan_id",
              "pending_plan_id", "pending_change_at"):
        check(f"billing status still has '{k}'", k in data, str(list(data.keys()))[:120])
    check("guests cannot call refresh",
          rcv.BillingRefreshView.as_view()(f.post("/api/billing/refresh/")).status_code in (401, 403))


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
                       ALLOWED_HOSTS=["*", "testserver"]):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_rc_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
