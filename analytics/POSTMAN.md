# Pathzi Analytics — Postman Guide

A ready-to-import Postman collection for the analytics ingest endpoints.

**File:** `Pathzi_Analytics.postman_collection.json` (project root)

---

## 1. Import

1. Open Postman → **Import** → drag in `Pathzi_Analytics.postman_collection.json`.
2. The collection **"Pathzi Analytics — Ingest API"** appears with two folders:
   **Activity** and **Consent**.

## 2. Set the two variables

Open the collection → **Variables** tab and set:

| Variable | Example | Notes |
|---|---|---|
| `base_url` | `http://localhost:8000` | or `https://pathzi.co.uk` |
| `access_token` | `eyJhbGci...` | A valid JWT access token |

The collection is configured with **Bearer auth** using `{{access_token}}`, so
every request sends `Authorization: Bearer <token>` automatically. Click
**Save** after editing variables.

> Get a token by logging in via your auth endpoint (e.g. `POST /accounts/login/`)
> and copying the `access` token into `access_token`.

---

## 3. What's included

### Folder: Activity → `POST /analytics/activity/`

| Request | Body | Expected |
|---|---|---|
| **one event (minimal)** | 1 event, only `activity_type` + `career_id` | `202 { queued: 1 }` |
| **one event (full body)** | 1 event with all fields (`route_id`, `activity_value`, `metadata`) | `202 { queued: 1 }` |
| **multiple events (batch)** | 5 mixed events | `202 { queued: 5 }` |
| **invalid: backend-only type** | `career_saved` (not allowed here) | `400` |
| **invalid: empty batch** | `events: []` | `400` |

### Folder: Consent → `POST /analytics/consent/`

| Request | Body | Expected |
|---|---|---|
| **minimal** | `provider_name` + `contact_email` | `201 { lead_id }` |
| **full body** | + `career_id`, `provider_type` | `201 { lead_id }` (also a bad-email `400` example) |

Each request has **saved example responses** (open a request → **Examples**
dropdown, top-right) so you can see the exact success and error shapes without
sending anything.

---

## 4. Body variations at a glance

**Minimal activity (one event):**
```json
{ "events": [ { "activity_type": "career_viewed", "career_id": 2336 } ] }
```

**Full activity (one event):**
```json
{ "events": [
  { "activity_type": "route_clicked", "career_id": 2336, "route_id": 4,
    "activity_value": "University",
    "metadata": { "source": "career_detail", "position": 2, "session_id": "abc123" } }
] }
```

**Batch (multiple events):**
```json
{ "events": [
  { "activity_type": "career_viewed", "career_id": 2336, "metadata": {"source":"swipe_deck","position":4} },
  { "activity_type": "career_swiped_right", "career_id": 2336, "metadata": {"source":"swipe_deck","position":4} },
  { "activity_type": "provider_link_clicked", "career_id": 2336, "activity_value": "UCAS", "metadata": {"provider_type":"university"} }
] }
```

**Consent (minimal):**
```json
{ "provider_name": "City College", "contact_email": "user@example.com" }
```

**Consent (full):**
```json
{ "career_id": 2336, "provider_name": "City College", "provider_type": "college", "contact_email": "user@example.com" }
```

---

## 5. Responses

**Activity success — `202 Accepted`**
```json
{ "status": true, "queued": 5 }
```

**Activity error — `400` (disallowed type)**
```json
{ "events": { "0": { "activity_type": ["Unsupported activity_type 'career_saved'. Allowed: [...]"] } } }
```

**Consent success — `201 Created`**
```json
{ "status": true, "message": "Consent recorded.", "lead_id": 17, "consent_at": "2026-06-16T13:40:00Z" }
```

**Auth error — `401`** (missing/invalid token)
```json
{ "detail": "Authentication credentials were not provided." }
```

**Throttled — `429`** (over 120 requests/min)
```json
{ "detail": "Request was throttled. Expected available in N seconds." }
```

---

## 6. Tester notes

- Activity events are **asynchronous**: `202` is instant, but the row appears in
  reports within **~30 seconds** (background flush). The backend worker must be
  running for them to persist.
- Consent is **synchronous**: the `lead_id` in the `201` is created immediately.
- A non-existent `career_id` does **not** fail an activity request — the event
  is stored without the career link.
- Never put emails/phones in `metadata`; the server redacts them to `[redacted]`.

> Full field-level reference: see `analytics/API.md`.
