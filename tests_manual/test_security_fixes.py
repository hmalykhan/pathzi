"""
The six security findings from 11 Sep.

Each check tries the attack and asserts it now fails. Where a fix could
break the app, there is also a check that the app's own use still works.

Run:  PYTHONPATH=. python tests_manual/test_security_fixes.py
"""
import os, sys, uuid, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from django.conf import settings
from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from django.urls import resolve, Resolver404
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import UserProfile
from billing.services.access import ensure_account_identity

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()


def mk(tag, staff=False):
    e = f"ut_sec_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e,
                                 password="x"*12, is_staff=staff)
    p = UserProfile.objects.create(appuser=u, age=17, city="Manchester",
                                   address="12 High Street", zip_code="M1 2AB",
                                   lat="53.480759", lng="-2.242631")
    ensure_account_identity(p)
    return u, p


def run():
    print("--- #1 PII leak: user_profile on catalogue items ---")
    from courses.models import Course
    from courses.api.serializer import CoursesSerializer
    from courses.models import UserSavedCourse

    saver, saver_profile = mk("saver")
    course = Course.objects.first()
    UserSavedCourse.objects.create(user_profile=saver_profile, course_id=course.course_id)

    # A guest asking for this course. DRF gives an unauthenticated request
    # AnonymousUser, never None.
    from django.contrib.auth.models import AnonymousUser
    guest_req = f.get("/careers/1/courses/")
    guest_req.user = AnonymousUser()
    data = CoursesSerializer(course, context={"request": guest_req}).data
    check("guests see NO profiles", data.get("user_profile") == [],
          str(data.get("user_profile"))[:80])
    check("the key still exists (app cannot crash on a missing field)",
          "user_profile" in data)

    # An ordinary signed-in user
    other, _ = mk("other")
    req = f.get("/careers/1/courses/"); req.user = other
    data = CoursesSerializer(course, context={"request": req}).data
    check("ordinary users see NO profiles", data.get("user_profile") == [])

    # Staff
    admin, _ = mk("admin", staff=True)
    req = f.get("/careers/1/courses/"); req.user = admin
    data = CoursesSerializer(course, context={"request": req}).data
    check("staff still see the data", len(data.get("user_profile") or []) >= 1,
          str(len(data.get("user_profile") or [])))

    # The same guard on the other two
    from jobs.api.serializers import JobsSerializer
    from apprenticeship.api.serializers import ApprenticeshipSerializer
    for name, ser in (("jobs", JobsSerializer), ("apprenticeships", ApprenticeshipSerializer)):
        check(f"{name} serializer has the guard too", hasattr(ser, "_may_see_profiles"))

    print("\n--- #2 /accounts/users/ ---")
    from accounts.views import UserAPI
    r = UserAPI.as_view()(f.get("/accounts/users/"))
    check("guests refused", r.status_code in (401, 403), f"got {r.status_code}")
    req = f.get("/accounts/users/"); force_authenticate(req, user=other)
    check("ordinary users refused", UserAPI.as_view()(req).status_code == 403)
    req = f.get("/accounts/users/"); force_authenticate(req, user=admin)
    check("staff allowed", UserAPI.as_view()(req).status_code == 200)

    print("\n--- #3 raising your own usage limit ---")
    from usage_limits.views import UpdateSwipeLimitView
    req = f.patch("/usage-limits/update-limit/", {"max_swipes": 9999}, format="json")
    force_authenticate(req, user=other)
    check("ordinary users refused", UpdateSwipeLimitView.as_view()(req).status_code == 403)

    print("\n--- #4 account enumeration on forgot-password ---")
    from accounts.views import ForgotPasswordAPI
    view = ForgotPasswordAPI.as_view(throttle_classes=[])
    unknown = view(f.post("/accounts/forgot_password/",
                          {"email": "definitely-not-a-user@example.invalid"}, format="json"))
    check("unknown email gets 200", unknown.status_code == 200, f"got {unknown.status_code}")
    check("and does NOT say the email is unknown",
          "does not exist" not in str(unknown.data).lower(), str(unknown.data)[:90])
    check("it claims an OTP was sent, like the real case",
          unknown.data.get("status") is True and "OTP sent" in unknown.data.get("message", ""))

    print("\n--- #5 the broken route ---")
    try:
        resolve("/accounts/1/create_qualification")
        check("broken route removed", False, "it still resolves")
    except Resolver404:
        check("broken route removed", True)

    print("\n--- #6 configuration ---")
    src = open("pathzi/settings.py").read()
    check("SECRET_KEY is read from the environment", 'SECRET_KEY = config(' in src)
    check("SECRET_KEY is no longer a bare literal assignment",
          "SECRET_KEY = 'django-insecure" not in src)
    check("DEBUG is read from the environment", 'DEBUG = config("DEBUG"' in src)
    check("DEBUG defaults to False", 'config("DEBUG", default=False' in src)
    check("JWT signs with its own key, so SECRET_KEY can be rotated later",
          'config("JWT_SIGNING_KEY"' in src)
    # The key committed to git from the first commit, identified by hash so
    # this file does not put the leaked value back into the repository.
    import hashlib
    LEAKED_SHA256 = "9055b6aa3ff6c0c2514b3ddddcd0750032aee8809c75f30bfd17b64680d5a515"
    def _is_leaked(value):
        return hashlib.sha256((value or "").encode()).hexdigest() == LEAKED_SHA256

    check("the leaked key is no longer SECRET_KEY", not _is_leaked(settings.SECRET_KEY))
    check("SECRET_KEY is a proper length", len(settings.SECRET_KEY) >= 50,
          str(len(settings.SECRET_KEY)))
    check("no key literal is left in settings.py",
          "django-insecure" not in open("pathzi/settings.py").read())
    # Tokens on people's phones were signed with the old key. It stays as
    # the JWT signing key so they keep working; only SECRET_KEY changed.
    check("JWT signing is separate from SECRET_KEY",
          settings.SIMPLE_JWT.get("SIGNING_KEY") != settings.SECRET_KEY)

    check("the leaked key signs nothing any more", not _is_leaked(
        settings.SIMPLE_JWT.get("SIGNING_KEY", "")))

    # The actual attack: anyone who read the key out of git could mint a
    # token for any user id and be logged in as them, no password needed.
    import time, jwt as pyjwt
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from accounts.authentication import RevocableJWTAuthentication

    LEAKED_KEY = os.environ.get("PATHZI_TEST_LEAKED_KEY", "")
    if LEAKED_KEY and _is_leaked(LEAKED_KEY):
        forged = pyjwt.encode(
            {"token_type": "access", "exp": int(time.time()) + 3600,
             "iat": int(time.time()), "jti": uuid.uuid4().hex, "user_id": other.id},
            LEAKED_KEY, algorithm="HS256")
        try:
            forged_ok = RevocableJWTAuthentication().authenticate(
                f.get("/", HTTP_AUTHORIZATION="Bearer " + forged)) is not None
        except Exception:
            forged_ok = False
        check("a token forged with the leaked key is REFUSED", not forged_ok)
    else:
        print("  (set PATHZI_TEST_LEAKED_KEY to also run the forgery check)")

    tok = str(RefreshToken.for_user(other).access_token)
    req = f.get("/", HTTP_AUTHORIZATION="Bearer " + tok)
    try:
        works = RevocableJWTAuthentication().authenticate(req) is not None
    except (InvalidToken, TokenError):
        works = False
    check("genuine tokens still work", works)


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_sec_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
