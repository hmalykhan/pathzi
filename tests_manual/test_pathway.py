"""
Server-side AI pathway: generate, store, save, list, regenerate.

Gemini is mocked. The point of these tests is the behaviour around the AI
call - caching, the saved flag, regeneration, and that a failure never
loses an existing pathway - not the model's wording.

Run:  PYTHONPATH=. python tests_manual/test_pathway.py
"""
import os, sys, json, uuid, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
import django; django.setup()
logging.disable(logging.CRITICAL)

from unittest.mock import patch
from django.db import transaction
from django.test import override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import UserProfile
from billing.services.access import ensure_account_identity
from careers.models import Career, UserCareerReport
from careers.views import CareersView
from careers.services import pathway as ps

RESULTS = []
def check(label, cond, extra=""):
    RESULTS.append(bool(cond)); print(("PASS" if cond else "FAIL"), label, extra)

f = APIRequestFactory()
PATHWAY = CareersView.as_view({"get": "pathway"})
SAVE = CareersView.as_view({"post": "pathway_save", "delete": "pathway_save"})
REPORTS = CareersView.as_view({"get": "reports"})

FAKE = {
    "summary": {
        "title": "Radiographer",
        "subtitle": "Use imaging to help diagnose patients",
        "totalTimelineEstimate": "4-6 years",
        "steps": [
            {"stepNumber": 1, "title": "Complete A-levels including Biology", "estimatedTime": "", "isActive": True},
            {"stepNumber": 2, "title": "Earn a BSc (Hons) Diagnostic Radiography", "estimatedTime": "", "isActive": False},
        ],
    },
    "version": ps.PROMPT_VERSION,
    "generated_by": "server",
}


def mk(tag):
    e = f"ut_pw_{tag}_{uuid.uuid4().hex[:6]}@example.invalid"
    u = User.objects.create_user(username=e.split("@")[0], email=e, password="x"*12)
    p = UserProfile.objects.create(appuser=u, age=17, education_level="GCSEs",
                                   discipline="Science", city="Manchester",
                                   address="12 High Street", zip_code="M1 2AB")
    ensure_account_identity(p)
    return u, p


def get_pathway(user, career_id, **params):
    q = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    req = f.get(f"/careers/{career_id}/pathway/{q}")
    force_authenticate(req, user=user)
    return PATHWAY(req, pk=str(career_id))


def run():
    career = Career.objects.exclude(job_description="").first()
    u, p = mk("main")

    print("--- generating ---")
    with patch.object(ps, "generate", return_value=FAKE) as gen:
        r = get_pathway(u, career.id)
    check("returns 200", r.status_code == 200, f"got {r.status_code}")
    check("generated on first call", r.data.get("generated") is True)
    check("has steps", len(r.data.get("steps") or []) == 2)
    check("has timeline", r.data.get("total_timeline_estimate") == "4-6 years")
    check("current_step from the active step", r.data.get("current_step") == 1)
    check("NOT saved by default", r.data.get("saved") is False)
    check("it was stored", UserCareerReport.objects.filter(user_profile=p, career=career).exists())

    print("\n--- per-career progress, derived not ticked ---")
    pr = r.data.get("progress") or {}
    check("progress is in the same report (no extra call)", bool(pr), str(pr))
    check("total_steps counted", pr.get("total_steps") == 2, str(pr.get("total_steps")))
    check("on step 1 of 2, nothing completed yet", pr.get("completed_steps") == 0)
    check("percent is 0 at the start", pr.get("percent") == 0, str(pr.get("percent")))
    steps = r.data.get("steps") or []
    check("step 1 flagged current", steps[0].get("current") is True)
    check("step 1 not flagged completed", steps[0].get("completed") is False)
    check("step 2 not current", steps[1].get("current") is False)

    # A pathway where the student is further along.
    LATER = {"summary": {**FAKE["summary"], "steps": [
        {"stepNumber": 1, "title": "a", "estimatedTime": "", "isActive": False},
        {"stepNumber": 2, "title": "b", "estimatedTime": "", "isActive": False},
        {"stepNumber": 3, "title": "c", "estimatedTime": "", "isActive": True},
        {"stepNumber": 4, "title": "d", "estimatedTime": "", "isActive": False},
    ]}, "version": ps.PROMPT_VERSION, "generated_by": "server"}
    pr2 = ps.progress(LATER)
    check("on step 3 of 4 -> 2 completed", pr2["completed_steps"] == 2, str(pr2))
    check("percent rounds sensibly (50%)", pr2["percent"] == 50, str(pr2["percent"]))
    flagged = ps.steps_with_completion(LATER)
    check("earlier steps marked done", flagged[0]["completed"] and flagged[1]["completed"])
    check("the active one is current, not completed",
          flagged[2]["current"] is True and flagged[2]["completed"] is False)
    check("later steps neither", not flagged[3]["completed"] and not flagged[3]["current"])
    check("an empty pathway gives zeros, not a crash",
          ps.progress({})["total_steps"] == 0 and ps.progress({})["percent"] == 0)

    print("\n--- second visit must not pay for another generation ---")
    with patch.object(ps, "generate", return_value=FAKE) as gen:
        r2 = get_pathway(u, career.id)
    check("no AI call the second time", gen.call_count == 0, f"called {gen.call_count}x")
    check("still returns the pathway", r2.status_code == 200 and len(r2.data["steps"]) == 2)
    check("reported as not newly generated", r2.data.get("generated") is False)

    print("\n--- it is not in the saved list until the user saves ---")
    req = f.get("/careers/reports/"); force_authenticate(req, user=u)
    lst = REPORTS(req)
    check("saved list is empty", lst.status_code == 200 and len(lst.data) == 0,
          f"got {len(lst.data)}")

    req = f.post(f"/careers/{career.id}/pathway/save/"); force_authenticate(req, user=u)
    sv = SAVE(req, pk=str(career.id))
    check("saving works", sv.status_code == 200 and sv.data["saved"] is True)

    req = f.get("/careers/reports/"); force_authenticate(req, user=u)
    lst = REPORTS(req)
    check("now it appears in the saved list", len(lst.data) == 1, f"got {len(lst.data)}")
    check("the list carries the pathway", bool(lst.data[0]["my_report"]["report"]))

    print("\n--- un-saving hides it but keeps the work ---")
    req = f.delete(f"/careers/{career.id}/pathway/save/"); force_authenticate(req, user=u)
    un = SAVE(req, pk=str(career.id))
    check("unsave works", un.status_code == 200 and un.data["saved"] is False)
    req = f.get("/careers/reports/"); force_authenticate(req, user=u)
    check("gone from the saved list", len(REPORTS(req).data) == 0)
    check("but the row is still there (no regeneration needed)",
          UserCareerReport.objects.filter(user_profile=p, career=career).exists())

    print("\n--- regenerating when the profile changes ---")
    before = ps.profile_fingerprint(p)
    p.education_level = "A-levels"; p.save(update_fields=["education_level"])
    p.refresh_from_db()
    after = ps.profile_fingerprint(p)
    check("education level changes the fingerprint", before != after)

    with patch.object(ps, "generate", return_value=FAKE) as gen:
        get_pathway(u, career.id)
    check("a changed profile triggers regeneration", gen.call_count == 1, f"called {gen.call_count}x")

    p.address = "99 Other Road"; p.save(update_fields=["address"])
    p.refresh_from_db()
    check("changing address does NOT change the fingerprint",
          ps.profile_fingerprint(p) == after)
    with patch.object(ps, "generate", return_value=FAKE) as gen:
        get_pathway(u, career.id)
    check("so no needless regeneration", gen.call_count == 0, f"called {gen.call_count}x")

    print("\n--- saving survives regeneration ---")
    req = f.post(f"/careers/{career.id}/pathway/save/"); force_authenticate(req, user=u)
    SAVE(req, pk=str(career.id))
    with patch.object(ps, "generate", return_value=FAKE):
        get_pathway(u, career.id, refresh="true")
    row = UserCareerReport.objects.get(user_profile=p, career=career)
    check("regenerating does not un-save the user's pathway", row.user_saved is True)

    print("\n--- when the AI is down ---")
    u2, p2 = mk("down")
    with patch.object(ps, "generate", side_effect=ps.PathwayUnavailable("no")):
        r = get_pathway(u2, career.id)
    check("a clear 503, not a crash", r.status_code == 503, f"got {r.status_code}")
    check("with a code the app can use", r.data.get("code") == "pathway_unavailable")

    with patch.object(ps, "generate", return_value=FAKE):
        get_pathway(u2, career.id)
    p2.education_level = "Degree"; p2.save(update_fields=["education_level"])
    with patch.object(ps, "generate", side_effect=ps.PathwayUnavailable("no")):
        r = get_pathway(u2, career.id)
    check("an existing pathway is shown rather than an error", r.status_code == 200)
    check("and it is flagged stale", r.data.get("stale") is True)

    print("\n--- privacy: the prompt must not carry a home address ---")
    prompt = ps.build_prompt(p, career)
    check("street address is NOT in the prompt", "High Street" not in prompt and "Other Road" not in prompt)
    check("postcode is NOT in the prompt", "M1 2AB" not in prompt)
    check("town IS in the prompt", "Manchester" in prompt)

    print("\n--- the shape is repaired, never trusted ---")
    fixed = ps._normalise({"title": "X", "subtitle": "y", "totalTimelineEstimate": "2 years",
                           "steps": [{"stepNumber": 1, "title": "a", "isActive": False},
                                     {"stepNumber": 2, "title": "b", "isActive": False}]}, career)
    check("with no active step, one is forced",
          sum(1 for s in fixed["summary"]["steps"] if s["isActive"]) == 1)
    many = ps._normalise({"title": "X", "subtitle": "y", "totalTimelineEstimate": "2",
                          "steps": [{"stepNumber": i, "title": f"s{i}", "isActive": True} for i in range(1, 9)]}, career)
    check("never more than 5 steps", len(many["summary"]["steps"]) == 5)
    check("and still exactly one active",
          sum(1 for s in many["summary"]["steps"] if s["isActive"]) == 1)
    try:
        ps._normalise({"title": "X", "steps": []}, career)
        check("an empty pathway is refused", False, "no error raised")
    except ps.PathwayUnavailable:
        check("an empty pathway is refused", True)

    print("\n--- guests ---")
    check("a guest cannot generate", PATHWAY(f.get(f"/careers/{career.id}/pathway/"),
                                             pk=str(career.id)).status_code in (401, 403))


with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}):
    with transaction.atomic():
        try:
            run()
        finally:
            transaction.set_rollback(True)

left = User.objects.filter(email__startswith="ut_pw_").count()
print("\n" + ("ALL PASS" if all(RESULTS) else f"{RESULTS.count(False)} FAILED"),
      f"| {len(RESULTS)} checks | test users left: {left}")
