"""
Free tier after the trial.

The most important checks here are the ones with the flag OFF: the whole
point of the switch is that deploying this changes nothing until the new
app is live.

Run:  PYTHONPATH=. python tests_manual/test_free_tier.py
"""
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

from accounts.models import UserProfile
from billing.models import BillingProfile
from billing.services.access import access_for, ensure_account_identity
from careers.models import Career, UserExploredCareer, UserSavedCareer
from careers.views import CareersView

# The full-list path fires a Celery task to rebuild recommendations. That
# needs the Redis broker, which is not reachable from a dev machine, so it
# is stubbed - we are testing which careers come back, not the rebuild.
import careers.views as _cv
from unittest.mock import patch
_celery_stub = patch.object(_cv, "trigger_recs_debounced", lambda *a, **k: None)
_celery_stub.start()

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()
LIST = CareersView.as_view({"get": "list"})

def mk(tag, expired=False):
    e = f"ut_ft_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)
    if expired:
        p.trial_started_at = timezone.now() - timedelta(days=30)
        p.trial_ends_at = timezone.now() - timedelta(days=23)
        p.save(update_fields=["trial_started_at", "trial_ends_at"])
    return u, p

def career_list(user):
    req = f.get("/careers/")
    force_authenticate(req, user=user)
    r = LIST(req)
    return r.status_code, (r.data if isinstance(r.data, list) else [])

def run():
    some = list(Career.objects.all().only("id")[:6])
    if len(some) < 4:
        print("SKIP: not enough careers in the database"); return

    print("--- flag OFF: nothing changes for anybody ---")
    u_exp, p_exp = mk("offexp", expired=True)
    UserExploredCareer.objects.create(user_profile=p_exp, career=some[0])
    check("the trial really has expired", access_for(u_exp)["has_access"] is False)

    with override_settings(PAYWALL_ENFORCED=False):
        code, data = career_list(u_exp)
        check("expired user still gets the full list (flag off)", code == 200 and len(data) > 1,
              f"status={code} got {len(data)} careers")

    print("\n--- flag ON: the free tier applies ---")
    with override_settings(PAYWALL_ENFORCED=True):
        code, data = career_list(u_exp)
        ids = [c["id"] for c in data]
        check("expired user now gets only what they explored", code == 200 and ids == [some[0].id],
              f"got {ids}")

        # explored + saved together
        UserSavedCareer.objects.create(user_profile=p_exp, career=some[1])
        code, data = career_list(u_exp)
        ids = sorted(c["id"] for c in data)
        check("explored AND saved careers both show", ids == sorted([some[0].id, some[1].id]),
              f"got {ids}")

        # a career they never touched must not appear
        check("a career they never touched is not shown", some[2].id not in ids)

        print("\n--- flag ON: people WITH access are untouched ---")
        u_trial, _ = mk("trial")
        check("trial user has access", access_for(u_trial)["has_access"] is True)
        code, data = career_list(u_trial)
        check("a user on trial still gets the full list", code == 200 and len(data) > 1,
              f"got {len(data)}")

        u_sub, p_sub = mk("sub", expired=True)
        BillingProfile.objects.create(user=u_sub, plan_id="monthly", subscription_status="active",
                                      current_period_end=timezone.now()+timedelta(days=20))
        u_sub = User.objects.get(pk=u_sub.pk)
        check("subscriber has access", access_for(u_sub)["has_access"] is True)
        code, data = career_list(u_sub)
        check("a paying subscriber gets the full list even after trial end",
              code == 200 and len(data) > 1, f"got {len(data)}")

        print("\n--- awkward cases ---")
        u_empty, _ = mk("empty", expired=True)
        code, data = career_list(u_empty)
        check("an expired user who explored nothing gets an empty list, not an error",
              code == 200 and data == [], f"status={code} got {len(data)}")

        r = LIST(f.get("/careers/"))
        check("guests are unaffected", r.status_code == 200)

        print("\n--- referral days count as access ---")
        u_ref, p_ref = mk("ref", expired=True)
        UserExploredCareer.objects.create(user_profile=p_ref, career=some[0])
        p_ref.referral_access_until = timezone.now() + timedelta(days=5)
        p_ref.save(update_fields=["referral_access_until"])
        check("referral days give access", access_for(u_ref)["has_access"] is True)
        code, data = career_list(u_ref)
        check("someone on referral days gets the full list", code == 200 and len(data) > 1,
              f"got {len(data)}")

with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_ft_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
