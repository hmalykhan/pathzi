"""
Work style fields, the entry_requirements alias, and relevance ranking.

The important checks are the ones proving the DEFAULT behaviour did not
change: existing keys still present, and routes still nearest-first unless
the app explicitly asks for relevance.

Run:  PYTHONPATH=. python tests_manual/test_api_fields.py
"""
import os, sys, uuid, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from unittest.mock import patch
from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory, force_authenticate

import careers.views as cv
from careers.views import CareersView
from careers.models import Career
from accounts.models import UserProfile
from billing.services.access import ensure_account_identity
from careers.services.nearby_routes import rank_by_relevance, relevance_score, _words

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()
_stub = patch.object(cv, "trigger_recs_debounced", lambda *a, **k: None)
_stub.start()


class FakeItem:
    """Stands in for a course/job row, so ranking is tested without the DB."""
    def __init__(self, title, distance_km=None, detail=""):
        self.course_name = title
        self.distance_km = distance_km
        self.entry_reeq = detail


def run():
    print("--- 1. work style fields on the career list ---")
    e = f"ut_api_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=0)
    ensure_account_identity(p)

    req = f.get("/careers/"); force_authenticate(req, user=u)
    r = CareersView.as_view({"get": "list"})(req)
    check("career list still returns 200", r.status_code == 200, f"got {r.status_code}")
    check("career list still returns careers", isinstance(r.data, list) and len(r.data) > 0)

    card = r.data[0]
    for old_key in ("id", "category", "subcategory", "job_description", "dg_image_url", "salary"):
        check(f"card still has original key '{old_key}'", old_key in card)
    for new_key in ("work_style", "work_location", "work_social", "work_pace"):
        check(f"card now has '{new_key}'", new_key in card, str(card.get(new_key)))
    check("work_style has a real value (backfill ran)",
          card.get("work_style") in ("hands-on", "desk-based", "mixed"), str(card.get("work_style")))

    print("\n--- 2. career detail: work style + entry_requirements ---")
    career = Career.objects.exclude(work_style=None).first()
    req = f.get(f"/careers/{career.id}/"); force_authenticate(req, user=u)
    r = CareersView.as_view({"get": "retrieve"})(req, pk=career.id)
    d = r.data
    check("detail returns 200", r.status_code == 200, f"got {r.status_code}")
    for old_key in ("id", "career_type", "category", "job_slug", "how_to_become",
                    "college_entry_req", "apprenticeship_entry_req"):
        check(f"detail still has '{old_key}'", old_key in d)
    check("detail has work_style", d.get("work_style") is not None, str(d.get("work_style")))
    check("detail has entry_requirements", "entry_requirements" in d)
    er = d.get("entry_requirements") or {}
    check("entry_requirements has college/apprenticeship/summary",
          set(er) == {"college", "apprenticeship", "summary"}, str(list(er)))
    check("entry_requirements.summary is filled", bool(er.get("summary")))
    check("the raw columns are still there too (nothing replaced)",
          "college_entry_req" in d and "apprenticeship_entry_req" in d)

    print("\n--- 3. relevance ranking ---")
    items = [
        FakeItem("Construction (General)", distance_km=1.0),
        FakeItem("Carpentry and Joinery Level 2", distance_km=8.0, detail="GCSEs needed"),
        FakeItem("Hairdressing Level 1", distance_km=0.5),
    ]
    ranked = rank_by_relevance(items, jobname="Carpenter joiner", radius_miles=30)
    check("the matching course beats the nearer irrelevant one",
          ranked[0].course_name.startswith("Carpentry"),
          " > ".join(i.course_name[:22] for i in ranked))
    check("every ranked item carries a score",
          all(getattr(i, "relevance", None) is not None for i in ranked))
    check("scores are between 0 and 1",
          all(0.0 <= i.relevance <= 1.0 for i in ranked))

    near = FakeItem("Carpentry Level 2", distance_km=1.0)
    far = FakeItem("Carpentry Level 2", distance_km=25.0)
    check("with equal titles, nearer wins",
          relevance_score(near, _words("Carpenter"), 48) > relevance_score(far, _words("Carpenter"), 48))

    rich = FakeItem("Carpentry", distance_km=5.0, detail="5 GCSEs including maths")
    bare = FakeItem("Carpentry", distance_km=5.0)
    check("a row with real detail outranks an empty stub",
          relevance_score(rich, _words("Carpentry"), 48) > relevance_score(bare, _words("Carpentry"), 48))

    no_coords = FakeItem("Carpentry", distance_km=None)
    check("a row without coordinates still scores, does not crash",
          0 < relevance_score(no_coords, _words("Carpentry"), 48) < 1)

    print("\n--- 4. DEFAULT behaviour unchanged ---")
    from careers.services.nearby_routes import wants_relevance
    check("no sort param -> distance order (default)",
          wants_relevance(f.get("/careers/1/courses/")) is False)
    check("sort=distance -> still distance",
          wants_relevance(f.get("/careers/1/courses/?sort=distance")) is False)
    check("sort=relevance -> relevance",
          wants_relevance(f.get("/careers/1/courses/?sort=relevance")) is True)
    check("unknown sort value falls back to distance",
          wants_relevance(f.get("/careers/1/courses/?sort=banana")) is False)


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_api_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
