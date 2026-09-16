"""
Career pathways, generated on the server.

This used to run on the phone with an OpenAI key compiled into the app -
see AI_PATHWAY_GENERATION.md. Moving it here fixes the reasons that was a
problem, not just where the code lives:

  - the key never leaves the server;
  - the user's street address and postcode are no longer sent to a third
    party. Only their town goes in the prompt, and only to keep advice
    regional. Some of these users are under 18;
  - the reply is a structured schema, so a malformed answer cannot break
    the screen;
  - every generated pathway is stored, so opening a career twice does not
    pay to generate it twice.

The prompt is the mobile team's, with the location line narrowed.
"""
import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

PROMPT_VERSION = "2"
STEP_COUNT = 5
GENERATION_TIMEOUT_SECONDS = 30

# The only profile fields that change the answer. The fingerprint is built
# from these, so a user editing their address does not throw away a pathway,
# but changing education level does.
FINGERPRINT_FIELDS = ("age", "education_level", "discipline", "category")

PATHWAY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "totalTimelineEstimate": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stepNumber": {"type": "integer"},
                    "title": {"type": "string"},
                    "isActive": {"type": "boolean"},
                },
                "required": ["stepNumber", "title", "isActive"],
            },
        },
    },
    "required": ["title", "subtitle", "totalTimelineEstimate", "steps"],
}


def profile_fingerprint(profile):
    """A short hash of the profile fields a pathway actually depends on."""
    if profile is None:
        return ""
    parts = []
    for name in FINGERPRINT_FIELDS:
        value = getattr(profile, name, None)
        if isinstance(value, (list, tuple)):
            value = ",".join(sorted(str(v) for v in value))
        parts.append("%s=%s" % (name, value if value not in (None, "") else ""))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _age_range(age):
    try:
        age = int(age or 0)
    except (TypeError, ValueError):
        return "unknown"
    if age <= 0:
        return "unknown"
    for low, high in ((0, 15), (16, 18), (19, 21), (22, 25), (26, 35), (36, 50)):
        if low <= age <= high:
            return "%d-%d" % (low, high)
    return "50+"


def _career_context(career):
    """The career description the prompt is built from (doc section 3.2)."""
    sections = (
        ("HOW TO BECOME", getattr(career, "how_to_become", "")),
        ("COLLEGE ROUTE", getattr(career, "college", "")),
        ("COLLEGE ENTRY REQUIREMENTS", getattr(career, "college_entry_req", "")),
        ("APPRENTICESHIP ROUTE", getattr(career, "apprenticeship", "")),
        ("APPRENTICESHIP ENTRY REQUIREMENTS", getattr(career, "apprenticeship_entry_req", "")),
        ("JOB DESCRIPTION", getattr(career, "job_description", "")),
    )
    parts = ["%s:\n%s" % (label, (text or "").strip())
             for label, text in sections if (text or "").strip()]
    return "\n\n".join(parts) or "Full career details available."


def build_prompt(profile, career):
    """
    The mobile team's prompt, with one change: location is the town only.

    The original sent "12 High Street, M1 2AB". A postcode identifies a
    household; the advice only needs to know the region.
    """
    interests = getattr(profile, "category", None) or []
    if isinstance(interests, (list, tuple)):
        interests = ", ".join(str(i) for i in interests if i)

    town = (getattr(profile, "city", "") or "").strip() or "the UK"

    return """You are an experienced UK career mentor and educational advisor with deep
knowledge of the UK education system, apprenticeships, professional
qualifications, and career progression pathways. Write in British English.

INPUT DATA
User Profile:
- Age range: {age_range}
- Current education level: {education}
- Current field of study: {discipline}
- Interest areas: {interests}
- Region: {town} (UK)

Target Job:
- Job title: {job_title}
- Industry/Sector: {sector}
- Job description and requirements: {context}

TASK
Create a precise, UK-specific career roadmap from the user's current
position to the target role.

CRITICAL REQUIREMENTS
1. EXACTLY {step_count} STEPS.
2. BE SPECIFIC, NOT GENERIC. Name real qualifications:
   AVOID "Complete relevant qualifications"
   PROVIDE "Complete A-levels in Business Studies and Economics, or a BTEC
   Level 3 Extended Diploma in Business"
3. Use real UK qualifications: GCSEs, A-levels, BTECs, T-levels, NVQs,
   apprenticeship levels, foundation degrees, HNC/HND, named degrees and
   professional certifications. Give exact durations such as "6-12 months".
4. Mark exactly ONE step with isActive true - the user's immediate next
   action, judged from their profile.
5. Each step title is at most 200 characters, action-oriented.
6. totalTimelineEstimate, applied strictly by current education level so
   the same profile always gets the same answer:
   - No qualifications / GCSEs only -> "6-8 years"
   - A-levels / BTEC Level 3 -> "4-6 years"
   - HNC/HND (Level 4-5) -> "3-4 years"
   - Bachelor's degree in the field -> "2-3 years"
   - Bachelor's degree in another field -> "3-4 years"
   - Master's in the field -> "1-2 years"
   - Already has entry-level experience in the sector -> subtract one year
7. Base everything on the job description provided. Do not invent
   requirements it does not support.
""".format(
        age_range=_age_range(getattr(profile, "age", None)),
        education=getattr(profile, "education_level", None) or "not given",
        discipline=getattr(profile, "discipline", None) or "not given",
        interests=interests or "not given",
        town=town,
        job_title=getattr(career, "jobname", None) or "Career Opportunity",
        sector=getattr(career, "sub_type", None) or "General",
        context=_career_context(career)[:4000],
        step_count=STEP_COUNT,
    )


def _client():
    from google import genai
    key = getattr(settings, "GEMINI_API_KEY", "")
    if not key:
        raise PathwayUnavailable("AI is not configured.")
    return genai.Client(api_key=key)


class PathwayUnavailable(Exception):
    """Generation could not be done now. The caller should say 'try again'."""


def generate(profile, career):
    """
    Ask Gemini for a pathway. Returns the report dict to store.

    Raises PathwayUnavailable when the AI cannot be reached or gives
    something unusable - never returns a half-built pathway.
    """
    from google.genai import types

    prompt = build_prompt(profile, career)
    try:
        response = _client().models.generate_content(
            model=getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PATHWAY_SCHEMA,
                temperature=0.4,
                http_options=types.HttpOptions(timeout=GENERATION_TIMEOUT_SECONDS * 1000),
            ),
        )
        data = json.loads(response.text)
    except Exception as e:
        logger.warning("Pathway generation failed for career=%s: %s: %s",
                       getattr(career, "id", None), type(e).__name__, str(e)[:200])
        raise PathwayUnavailable("Could not build your pathway just now.") from e

    return _normalise(data, career)


def _normalise(data, career):
    """
    Make the model's answer safe to store and show.

    The old app trusted the reply and broke the screen when it was short or
    had no active step. Here the shape is repaired instead.
    """
    steps_in = data.get("steps") or []
    steps = []
    for i, step in enumerate(steps_in[:STEP_COUNT], start=1):
        title = (step.get("title") or "").strip()
        if not title:
            continue
        steps.append({
            "stepNumber": i,
            "title": title[:200],
            "estimatedTime": "",
            "isActive": bool(step.get("isActive")),
        })

    if not steps:
        raise PathwayUnavailable("The pathway came back empty.")

    # Exactly one active step, always - the screen marks "YOU ARE HERE" from it.
    active = [s for s in steps if s["isActive"]]
    if len(active) != 1:
        for s in steps:
            s["isActive"] = False
        (active[0] if active else steps[0])["isActive"] = True

    return {
        "summary": {
            "title": (data.get("title") or getattr(career, "jobname", "") or "").strip(),
            "subtitle": (data.get("subtitle") or "").strip()[:120],
            "totalTimelineEstimate": (data.get("totalTimelineEstimate") or "").strip(),
            "steps": steps,
        },
        "version": PROMPT_VERSION,
        "generated_by": "server",
    }


def current_step(report):
    for step in ((report or {}).get("summary") or {}).get("steps") or []:
        if step.get("isActive"):
            return step.get("stepNumber")
    return 1
