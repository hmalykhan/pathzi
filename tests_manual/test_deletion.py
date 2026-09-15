"""Account deletion: it removes the right things, and damages nothing else."""
import os, sys, uuid, logging
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import UserProfile, Coordinates, UserEmbedding
from accounts.account_deletion import DeleteMyAccountView
from billing.models import BillingProfile, ReferralCode, ReferralCredit
from billing.services import referrals
from billing.services.access import ensure_account_identity

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()

def mk(tag):
    e = f"ut_del_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)
    return u, p

def delete_account(user):
    req = f.delete("/accounts/me/")
    force_authenticate(req, user=user)
    return DeleteMyAccountView.as_view()(req)

def run():
    print("--- a plain deletion ---")
    u, p = mk("plain")
    uid, pid = u.id, p.id
    Coordinates.objects.create(user_profile=p, title="Home", latitude=52.4, longitude=-1.9)
    r = delete_account(u)
    check("returns 200", r.status_code == 200, f"got {r.status_code}")
    check("says it is deleted", r.data["data"]["deleted"] is True)
    check("the user row is gone", not User.objects.filter(pk=uid).exists())
    check("the profile is gone", not UserProfile.objects.filter(pk=pid).exists())
    check("their saved locations are gone", not Coordinates.objects.filter(user_profile_id=pid).exists())
    check("no store subscription to warn about", r.data["data"]["had_active_subscription"] is False)
    check("no manage_url when nothing is running", r.data["data"]["manage_url"] is None)

    print("\n--- deleting while still subscribed ---")
    u2, p2 = mk("subbed")
    BillingProfile.objects.create(user=u2, plan_id="monthly", subscription_status="active",
                                  current_period_end=timezone.now()+timedelta(days=20), store="apple")
    r = delete_account(u2)
    check("the account is still deleted (never blocked)", not User.objects.filter(pk=u2.id).exists())
    check("but the response warns the subscription is live",
          r.data["data"]["had_active_subscription"] is True)
    check("and points at Apple's cancel screen",
          r.data["data"]["manage_url"] == "https://apps.apple.com/account/subscriptions",
          str(r.data["data"]["manage_url"]))
    check("the message tells the user to cancel", "cancel it in the store" in r.data["message"])

    print("\n--- THE BUG THAT WAS FOUND: deleting a referrer ---")
    referrer, _ = mk("ref")
    invitee, ip = mk("inv")
    code = referrals.create_code(referrer)
    referrals.redeem(code.code, invitee)
    check("the invitee earned a credit", ReferralCredit.objects.filter(user=invitee).count() == 1)

    delete_account(referrer)

    check("the referrer is gone", not User.objects.filter(pk=referrer.id).exists())
    check("the INVITEE keeps their credit row",
          ReferralCredit.objects.filter(user=invitee).count() == 1,
          f"got {ReferralCredit.objects.filter(user=invitee).count()}")
    check("the code row survives its creator", ReferralCode.objects.filter(pk=code.pk).exists())
    surviving = ReferralCode.objects.filter(pk=code.pk).first()
    check("the code no longer belongs to anyone", surviving.created_by_id is None)
    ip.refresh_from_db()
    check("the invitee keeps their free days", ip.referral_access_until is not None)
    check("the invitee's referral screen still totals correctly",
          referrals.summary_for(invitee)["days_earned"] == 7,
          str(referrals.summary_for(invitee)["days_earned"]))

    print("\n--- the deleted user's own referral data goes ---")
    u3, _ = mk("codes")
    mine = referrals.create_code(u3, channel="email", invited_email="friend@example.invalid")
    delete_account(u3)
    mine.refresh_from_db()
    check("their contact's email address is erased", mine.invited_email is None)
    check("their own credits are gone", ReferralCredit.objects.filter(user_id=u3.id).count() == 0)

    print("\n--- who may call it ---")
    r = DeleteMyAccountView.as_view()(f.delete("/accounts/me/"))
    check("a guest cannot delete anything", r.status_code in (401, 403), f"got {r.status_code}")

    u4, _ = mk("other")
    u5, _ = mk("victim")
    req = f.delete("/accounts/me/"); force_authenticate(req, user=u4)
    DeleteMyAccountView.as_view()(req)
    check("deleting yourself does not touch anyone else", User.objects.filter(pk=u5.id).exists())

with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_del_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
