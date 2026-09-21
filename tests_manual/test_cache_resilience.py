"""
Redis can go down without taking the site with it.

Upstash is both the cache and the Celery broker, so an outage used to raise
inside ordinary page requests - GET /careers/ among them, which is the home
screen. These tests simulate a total Redis failure and assert that pages
still answer 200.

The second half is just as important: when Redis is healthy, caching must
still actually cache. A "fix" that silently disabled caching would pass the
first half and quietly make the site slower.

Run:  PYTHONPATH=. python tests_manual/test_cache_resilience.py
"""
import os, sys, uuid, logging
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from unittest.mock import patch
from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

import pathzi.cache_utils as cu
from pathzi.cache_utils import cache_get, cache_set, cache_add, cache_delete, queue_task
from accounts.models import UserProfile
from billing.services.access import ensure_account_identity
from careers.views import CareersView
from careers.services.recommendation_triggers import trigger_recs_debounced

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()
LIST = CareersView.as_view({"get": "list"})


class DeadRedis:
    """Every operation fails, the way an unreachable Upstash does."""
    def get(self, *a, **k):    raise ConnectionError("Error -2 connecting to upstash.io:6379")
    def set(self, *a, **k):    raise ConnectionError("Error -2 connecting to upstash.io:6379")
    def add(self, *a, **k):    raise ConnectionError("Error -2 connecting to upstash.io:6379")
    def delete(self, *a, **k): raise ConnectionError("Error -2 connecting to upstash.io:6379")


def mk(tag):
    e = f"ut_cache_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)
    return u, p


def run():
    user, profile = mk("user")

    print("--- Redis completely down ---")
    with patch.object(cu, "cache", DeadRedis()):
        check("cache_get returns a miss instead of raising", cache_get("any-key") is None)
        check("cache_get honours its default", cache_get("any-key", "fallback") == "fallback")
        check("cache_set reports failure instead of raising", cache_set("k", "v") is False)
        check("cache_delete reports failure instead of raising", cache_delete("k") is False)
        check("cache_add says the lock was NOT taken", cache_add("lock") is False)

        # The broker is Redis too, so queueing must fail safely.
        def explodes(*a, **k):
            raise ConnectionError("broker unreachable")
        check("queue_task swallows a broker outage", queue_task(explodes) is False)

        check("trigger_recs_debounced returns False rather than raising",
              trigger_recs_debounced(user.id) is False)

        # THE ORIGINAL BUG: this used to raise and 500 the home screen.
        req = f.get("/careers/"); force_authenticate(req, user=user)
        r = LIST(req)
        check("GET /careers/ still answers 200 with Redis down", r.status_code == 200,
              f"got {r.status_code}")
        check("and still returns careers", isinstance(r.data, list) and len(r.data) > 0,
              f"got {len(r.data) if isinstance(r.data, list) else type(r.data)}")

        r = LIST(f.get("/careers/"))
        check("guests are fine too", r.status_code == 200, f"got {r.status_code}")

    print("\n--- auth endpoints must answer with Redis down ---")
    # DRF's throttles call the cache directly, so they never went through
    # cache_utils. With Redis unreachable they raised BEFORE the view ran,
    # and every throttled endpoint returned 500 - login and sign-up included.
    from accounts.views import AppleMobileAuthAPI, GoogleMobileAuthAPI, ForgotPasswordAPI
    with patch.object(cu, "cache", DeadRedis()):
        from django.core.cache import cache as django_cache
        with patch.object(django_cache, "get", side_effect=ConnectionError("redis down")), \
             patch.object(django_cache, "set", side_effect=ConnectionError("redis down")):
            for label, view, body in (
                ("apple", AppleMobileAuthAPI, {"identity_token": "bad"}),
                ("google", GoogleMobileAuthAPI, {"id_token": "bad"}),
                ("forgot_password", ForgotPasswordAPI, {"email": "nobody@example.invalid"}),
            ):
                try:
                    r = view.as_view()(f.post("/x/", body, format="json"))
                    ok = r.status_code < 500
                except Exception:
                    ok = False
                check(f"{label} answers rather than 500ing", ok)

    print("\n--- Redis healthy: caching must still work ---")
    with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
        from django.core.cache import cache as real_cache
        real_cache.clear()
        key = "ut_cache_probe_" + uuid.uuid4().hex[:8]

        check("a value written is a value read back",
              cache_set(key, {"hello": 1}) is True and cache_get(key) == {"hello": 1})
        check("a missing key is still a miss", cache_get("ut_cache_absent") is None)
        check("the first lock is taken", cache_add(key + "_lock", True, 60) is True)
        check("the same lock cannot be taken twice", cache_add(key + "_lock", True, 60) is False)
        check("delete really deletes", cache_delete(key) is True and cache_get(key) is None)
        check("queue_task reports success when the broker works",
              queue_task(lambda *a, **k: None) is True)

        with patch("careers.services.recommendation_triggers.update_embedding_and_recs_task") as task:
            first = trigger_recs_debounced(user.id)
            second = trigger_recs_debounced(user.id)
            check("a rebuild is queued the first time", first is True)
            check("and debounced the second time", second is False)
            check("the task was sent exactly once", task.delay.call_count == 1,
                  f"called {task.delay.call_count}x")


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_cache_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
