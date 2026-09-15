"""
Referral regression suite.

Kept in the repo, not the scratchpad: the scratchpad is wiped between
sessions, and this is the proof that referrals still behave after changes
elsewhere (it caught nothing the day it was written - it exists for the
day something else moves under it).

Run:  PYTHONPATH=. python tests_manual/test_referrals.py
"""
import os, sys, uuid, logging
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from unittest.mock import patch
from django.conf import settings
from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import UserProfile
from billing.models import BillingProfile, ReferralCode, ReferralCredit
from billing.services import referrals
from billing.services.access import access_for, ensure_account_identity
import accounts.views as av
import billing.referral_views as rv

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()

def mk(tag):
    e = f"ut_ref_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)
    return u, p

def signup(email, code=None):
    body = {"username": email.split("@")[0], "email": email,
            "password": "N3w-Secure-Pass!", "password2": "N3w-Secure-Pass!"}
    if code is not None:
        body["referral_code"] = code
    return av.SignUpAPI.as_view()(f.post("/accounts/signup/", body, format="json"))

def run():
    print("--- a referral that works ---")
    referrer, _ = mk("referrer")
    code = referrals.create_code(referrer)
    check("code looks right", code.code.startswith("PTH-") and len(code.code) == 10, code.code)
    check("code starts pending", code.status == "pending")

    email = f"ut_ref_inv_{uuid.uuid4().hex[:6]}@example.invalid"
    r = signup(email, code.code)
    invitee = User.objects.get(email=email)
    check("sign-up succeeded", r.status_code == 201)
    check("the referral applied", r.data["data"]["referral"]["applied"] is True)
    check("invitee has 14 days (7 trial + 7 bonus)",
          access_for(invitee)["days_remaining"] == 14, str(access_for(invitee)["days_remaining"]))
    check("referrer has 14 days too", access_for(referrer)["days_remaining"] == 14)
    check("both sides are in the ledger", ReferralCredit.objects.filter(code=code).count() == 2)

    print("\n--- the rules still hold ---")
    r = signup(f"ut_ref_2_{uuid.uuid4().hex[:6]}@example.invalid", code.code)
    check("a used code cannot be reused",
          r.status_code == 201 and r.data["data"]["referral"]["code"] == "referral_code_used")

    own = referrals.create_code(referrer)
    try:
        referrals.redeem(own.code, referrer); check("cannot use your own code", False)
    except referrals.ReferralError as e:
        check("cannot use your own code", e.code == "referral_code_own", e.code)

    again = referrals.create_code(referrer)
    try:
        referrals.redeem(again.code, invitee); check("only referred once", False)
    except referrals.ReferralError as e:
        check("only referred once", e.code == "referral_already_credited", e.code)

    expired = referrals.create_code(referrer)
    expired.expires_at = timezone.now() - timedelta(minutes=1)
    expired.save(update_fields=["expires_at"])
    r = signup(f"ut_ref_3_{uuid.uuid4().hex[:6]}@example.invalid", expired.code)
    check("an expired code is refused", r.data["data"]["referral"]["code"] == "referral_code_expired")

    r = signup(f"ut_ref_4_{uuid.uuid4().hex[:6]}@example.invalid", "PTH-NOTREAL")
    check("an unknown code never blocks sign-up",
          r.status_code == 201 and r.data["data"]["referral"]["code"] == "referral_code_invalid")

    r = signup(f"ut_ref_5_{uuid.uuid4().hex[:6]}@example.invalid")
    check("no code at all still signs up fine",
          r.status_code == 201 and r.data["data"]["referral"]["applied"] is False)

    print("\n--- days earned while subscribed are banked ---")
    sub, subp = mk("sub")
    BillingProfile.objects.create(user=sub, plan_id="yearly", subscription_status="active",
                                  current_period_end=timezone.now()+timedelta(days=300))
    sub_code = referrals.create_code(sub)
    signup(f"ut_ref_6_{uuid.uuid4().hex[:6]}@example.invalid", sub_code.code)
    subp.refresh_from_db()
    check("the days went to the bank", subp.referral_days_banked == 7)
    check("the subscription was not shortened",
          access_for(User.objects.get(pk=sub.pk))["days_remaining"] == 300)

    bp = BillingProfile.objects.get(user=sub)
    bp.current_period_end = timezone.now() - timedelta(days=1)
    bp.save(update_fields=["current_period_end"])
    acc = access_for(User.objects.get(pk=sub.pk))
    check("once it lapses the banked days become access", acc["has_access"] is True)
    check("and the bank is emptied", acc["banked_referral_days"] == 0)

    print("\n--- the referral screen ---")
    req = f.post("/me/referral/codes/", {}, format="json"); force_authenticate(req, user=referrer)
    r = rv.ReferralCodeCreateView.as_view()(req)
    check("a new code can be made", r.status_code == 201)

    req = f.get("/me/referral"); force_authenticate(req, user=referrer)
    data = rv.ReferralSummaryView.as_view()(req).data["data"]
    check("one friend joined", data["friends_joined"] == 1, str(data["friends_joined"]))
    check("7 days earned", data["days_earned"] == 7, str(data["days_earned"]))
    check("one credit waiting to be shown", len(data["unseen_credits"]) == 1)

    cid = data["unseen_credits"][0]["id"]
    req = f.post(f"/me/referral/credits/{cid}/ack/", {}, format="json")
    force_authenticate(req, user=referrer)
    check("the popup can be acknowledged",
          rv.ReferralCreditAckView.as_view()(req, credit_id=cid).status_code == 200)

    req = f.get("/me/referral"); force_authenticate(req, user=referrer)
    check("and does not come back",
          len(rv.ReferralSummaryView.as_view()(req).data["data"]["unseen_credits"]) == 0)

    check("guests are refused",
          rv.ReferralSummaryView.as_view()(f.get("/me/referral")).status_code in (401, 403))

    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        from django.core import mail
        mail.outbox = []
        req = f.post("/me/referral/invite", {"email": "friend@example.invalid"}, format="json")
        force_authenticate(req, user=referrer)
        r = rv.ReferralInviteView.as_view()(req)
        check("an invite email is sent", r.status_code == 201 and len(mail.outbox) == 1)
        check("the email carries the code", r.data["data"]["code"] in mail.outbox[0].body)

with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_ref_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
