"""
Sign out other devices.

The most important checks are that ordinary users are untouched: this
changes the authentication class every request goes through, so a mistake
here logs everybody out.

Run:  PYTHONPATH=. python tests_manual/test_sign_out.py
"""
import os, sys, time, uuid, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken

from accounts.models import UserProfile
from accounts.authentication import RevocableJWTAuthentication
from accounts.sign_out_views import SignOutOtherDevicesView, revoke_all_tokens
from billing.services.access import ensure_account_identity

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()
auth = RevocableJWTAuthentication()


def mk(tag):
    e = f"ut_so_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="OldPass123!")
    p = UserProfile.objects.create(appuser=u, age=20)
    ensure_account_identity(p)
    return u, p


def token_for(user):
    r = RefreshToken.for_user(user)
    return str(r.access_token)


def accepts(access_token):
    """Does authentication accept this token?"""
    req = f.get("/", HTTP_AUTHORIZATION="Bearer " + access_token)
    try:
        return auth.authenticate(req) is not None
    except InvalidToken:
        return False


def run():
    print("--- ordinary users are unaffected ---")
    u, p = mk("normal")
    t = token_for(u)
    check("a normal token authenticates", accepts(t))
    check("tokens_valid_from is null for everyone by default", p.tokens_valid_from is None)
    check("still works on a second call", accepts(t))

    print("\n--- signing out other devices ---")
    u2, p2 = mk("multi")
    phone = token_for(u2)
    laptop = token_for(u2)
    check("phone works", accepts(phone))
    check("laptop works", accepts(laptop))

    time.sleep(1.1)                      # iat has whole-second resolution
    result = revoke_all_tokens(u2, keep_current=True)

    check("the old phone token is now refused", not accepts(phone))
    check("the old laptop token is now refused", not accepts(laptop))
    check("a fresh pair was issued", bool(result and result["access"]))
    check("the new token still works", accepts(result["access"]))

    p2.refresh_from_db()
    check("the cutoff was recorded", p2.tokens_valid_from is not None)

    print("\n--- and it is per user, not global ---")
    u3, _ = mk("bystander")
    other = token_for(u3)
    revoke_all_tokens(u2, keep_current=False)
    check("someone else's token is untouched", accepts(other))

    print("\n--- the endpoint ---")
    u4, _ = mk("endpoint")
    old = token_for(u4)
    time.sleep(1.1)
    req = f.post("/accounts/sign-out-other-devices/")
    from rest_framework.test import force_authenticate
    force_authenticate(req, user=u4)
    r = SignOutOtherDevicesView.as_view()(req)
    check("endpoint returns 200", r.status_code == 200, f"got {r.status_code}")
    check("it hands back a new token", bool(r.data["data"]["token"]["access"]))
    check("the old session is dead", not accepts(old))
    check("the new one works", accepts(r.data["data"]["token"]["access"]))

    r2 = SignOutOtherDevicesView.as_view()(f.post("/accounts/sign-out-other-devices/"))
    check("a guest cannot call it", r2.status_code in (401, 403), f"got {r2.status_code}")

    print("\n--- a token minted in the same second as the cutoff survives ---")
    u5, p5 = mk("sameinstant")
    result = revoke_all_tokens(u5, keep_current=True)
    check("the pair issued at the cutoff is accepted", accepts(result["access"]))

    print("\n--- a revoked user with no cutoff is not accidentally locked out ---")
    u6, p6 = mk("cleared")
    t6 = token_for(u6)
    time.sleep(1.1)          # else the token shares the cutoff's second and is kept by design
    revoke_all_tokens(u6, keep_current=False)
    check("token refused after revoke", not accepts(t6))
    p6.refresh_from_db(); p6.tokens_valid_from = None; p6.save(update_fields=["tokens_valid_from"])
    from pathzi.cache_utils import cache_delete
    from accounts.authentication import valid_from_cache_key
    cache_delete(valid_from_cache_key(u6.id))
    check("clearing the cutoff restores access", accepts(t6))


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_so_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
