"""
Generate an importable Postman collection (v2.1) for the Pathzi Analytics
ingest endpoints, with minimal/full bodies, single/batch variations, and
saved example responses.

Run: python scripts/gen_postman_collection.py
Output: Pathzi_Analytics.postman_collection.json  (project root)
"""

import json

ACTIVITY_URL = {
    "raw": "{{base_url}}/analytics/activity/",
    "host": ["{{base_url}}"],
    "path": ["analytics", "activity", ""],
}
CONSENT_URL = {
    "raw": "{{base_url}}/analytics/consent/",
    "host": ["{{base_url}}"],
    "path": ["analytics", "consent", ""],
}
HEADERS = [{"key": "Content-Type", "value": "application/json"}]


def body(obj):
    return {"mode": "raw", "raw": json.dumps(obj, indent=2),
            "options": {"raw": {"language": "json"}}}


def request(url, obj, desc=""):
    return {"method": "POST", "header": HEADERS, "url": url,
            "body": body(obj), "description": desc}


def response(name, code, status, obj, req):
    return {
        "name": name,
        "originalRequest": req,
        "status": status,
        "code": code,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "cookie": [],
        "body": json.dumps(obj, indent=2),
    }


def item(name, url, obj, desc, examples):
    req = request(url, obj, desc)
    return {"name": name, "request": req,
            "response": [response(n, c, s, b, req) for (n, c, s, b) in examples]}


# ---------- ACTIVITY requests ----------
act_one_min = item(
    "Activity — one event (minimal)", ACTIVITY_URL,
    {"events": [{"activity_type": "career_viewed", "career_id": 2336}]},
    "Smallest valid request: a single event with only the required activity_type "
    "(career_id recommended). Returns 202 and queues 1 event.",
    [("202 Accepted", 202, "Accepted", {"status": True, "queued": 1})],
)

act_one_full = item(
    "Activity — one event (full body)", ACTIVITY_URL,
    {"events": [{
        "activity_type": "route_clicked",
        "career_id": 2336,
        "route_id": 4,
        "activity_value": "University",
        "metadata": {"source": "career_detail", "position": 2, "session_id": "abc123"},
    }]},
    "A single event using every field: activity_type, career_id, route_id, "
    "activity_value and metadata.",
    [("202 Accepted", 202, "Accepted", {"status": True, "queued": 1})],
)

act_multi = item(
    "Activity — multiple events (batch)", ACTIVITY_URL,
    {"events": [
        {"activity_type": "career_viewed", "career_id": 2336,
         "metadata": {"source": "swipe_deck", "position": 4}},
        {"activity_type": "career_swiped_right", "career_id": 2336,
         "metadata": {"source": "swipe_deck", "position": 4}},
        {"activity_type": "career_viewed", "career_id": 2421,
         "metadata": {"source": "swipe_deck", "position": 5}},
        {"activity_type": "career_swiped_left", "career_id": 2421,
         "metadata": {"source": "swipe_deck", "position": 5}},
        {"activity_type": "provider_link_clicked", "career_id": 2336,
         "activity_value": "UCAS", "metadata": {"provider_type": "university"}},
    ]},
    "Batch of several events in one request (recommended — buffer on the client "
    "and flush in batches of up to 200).",
    [("202 Accepted", 202, "Accepted", {"status": True, "queued": 5})],
)

act_bad_type = item(
    "Activity — invalid: backend-only type (400)", ACTIVITY_URL,
    {"events": [{"activity_type": "career_saved", "career_id": 2336}]},
    "career_saved is recorded by the backend automatically and is rejected here.",
    [("400 Bad Request", 400, "Bad Request",
      {"events": {"0": {"activity_type": [
          "Unsupported activity_type 'career_saved'. Allowed: ['career_swiped_left', "
          "'career_swiped_right', 'career_viewed', 'connect_button_clicked', "
          "'provider_link_clicked', 'route_clicked', 'route_viewed']"]}}})],
)

act_empty = item(
    "Activity — invalid: empty batch (400)", ACTIVITY_URL,
    {"events": []},
    "An empty events list is rejected.",
    [("400 Bad Request", 400, "Bad Request",
      {"events": ["events must contain at least 1 event."]})],
)

# ---------- CONSENT requests ----------
con_min = item(
    "Consent — minimal", CONSENT_URL,
    {"provider_name": "City College", "contact_email": "user@example.com"},
    "Smallest valid consent: provider_name + contact_email.",
    [("201 Created", 201, "Created",
      {"status": True, "message": "Consent recorded.", "lead_id": 17,
       "consent_at": "2026-06-16T13:40:00Z"})],
)

con_full = item(
    "Consent — full body", CONSENT_URL,
    {"career_id": 2336, "provider_name": "City College",
     "provider_type": "college", "contact_email": "user@example.com"},
    "Consent with all fields including career_id and provider_type.",
    [("201 Created", 201, "Created",
      {"status": True, "message": "Consent recorded.", "lead_id": 18,
       "consent_at": "2026-06-16T13:41:00Z"}),
     ("400 Bad Request — bad email", 400, "Bad Request",
      {"contact_email": ["Enter a valid email address."]})],
)

collection = {
    "info": {
        "_postman_id": "f1a7c0de-aaaa-4bbb-8ccc-pathzianalytics01",
        "name": "Pathzi Analytics — Ingest API",
        "description": (
            "Analytics activity + consent ingest endpoints.\n\n"
            "SETUP:\n"
            "1. Set the collection variable `base_url` (e.g. http://localhost:8000 "
            "or https://pathzi.co.uk).\n"
            "2. Set `access_token` to a valid JWT access token (a staff/normal user).\n"
            "   The collection sends it as a Bearer token automatically.\n\n"
            "Activity events are queued and appear in reports within ~30 seconds. "
            "Consent is written immediately.\n\n"
            "Allowed activity_type (activity endpoint): career_viewed, "
            "career_swiped_right, career_swiped_left, route_viewed, route_clicked, "
            "provider_link_clicked, connect_button_clicked.\n"
            "Limits: 1-200 events/request, 50 metadata keys/event, 120 requests/min."
        ),
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}]},
    "variable": [
        {"key": "base_url", "value": "http://localhost:8000"},
        {"key": "access_token", "value": ""},
    ],
    "item": [
        {"name": "Activity",
         "item": [act_one_min, act_one_full, act_multi, act_bad_type, act_empty]},
        {"name": "Consent",
         "item": [con_min, con_full]},
    ],
}

out = "Pathzi_Analytics.postman_collection.json"
with open(out, "w") as f:
    json.dump(collection, f, indent=2)
print("WROTE", out)
