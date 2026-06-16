# Pathzi Analytics — Activity Ingest API

Reference for **frontend developers** and **QA testers**.

This documents how the mobile/web app reports user activity to the backend.
There are two public endpoints:

| Purpose | Method & path |
|---|---|
| Report UI activity events (batch) | `POST /analytics/activity/` |
| Record consent to be contacted | `POST /analytics/consent/` |

---

## 1. Authentication

Both endpoints require an **authenticated user**. Send the JWT access token:

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

- The backend reads the user **from the token** — never send a user id in the body; any `user_id` in the payload is ignored.
- Unauthenticated requests get **401 Unauthorized**.

---

## 2. `POST /analytics/activity/` — report events

Send a **batch of 1–200 events** in a single request. The server validates them,
queues them, and returns immediately. Events are written to the database
asynchronously and appear in reports **within ~30 seconds**.

### 2.1 Request body

```json
{
  "events": [
    {
      "activity_type": "career_viewed",
      "career_id": 2336,
      "metadata": { "source": "swipe_deck", "position": 4, "session_id": "abc123" }
    },
    {
      "activity_type": "career_swiped_right",
      "career_id": 2336,
      "metadata": { "source": "swipe_deck", "position": 4 }
    }
  ]
}
```

### 2.2 Event fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `activity_type` | string | **yes** | Must be one of the allowed values in §2.3 |
| `career_id` | integer | no | DB id of the career the action is about |
| `route_id` | integer | no | Education-route id (for route events) |
| `activity_value` | string | no | Optional label (e.g. provider name, route name) |
| `metadata` | object | no | Free-form context. Max **50 keys**. **No personal data** (see §5) |

### 2.3 Allowed `activity_type` values

This endpoint accepts **only frontend-fired** event types:

| activity_type | When the app sends it | Recommended fields |
|---|---|---|
| `career_viewed` | A career card is shown to the user | `career_id`, metadata: `source`, `position`, `session_id` |
| `career_swiped_right` | User swipes right / likes a career | `career_id`, metadata: `source`, `position` |
| `career_swiped_left` | User swipes left / skips a career | `career_id`, metadata: `source`, `position` |
| `route_viewed` | An education route is shown | `career_id`, `route_id`, metadata: `source` |
| `route_clicked` | User taps an education route | `career_id`, `route_id`, metadata: `source` |
| `provider_link_clicked` | User opens a provider link | `career_id`, `activity_value` = provider name, metadata: `provider_type`, `url` |
| `connect_button_clicked` | User taps a "connect" button | `career_id`, `activity_value` = provider name |

> **Do NOT send** these — they are recorded automatically by the backend and
> will be **rejected (400)**: `career_saved`, `career_unsaved`,
> `career_explored`, `career_unexplored`, `search_performed`.
> `consent_given` has its own endpoint (§3).

### 2.4 Success response — `202 Accepted`

```json
{ "status": true, "queued": 2 }
```

`queued` = number of events accepted into the processing queue.

### 2.5 Limits

| Limit | Value |
|---|---|
| Events per request | 1–200 |
| Metadata keys per event | 50 |
| Rate limit | 120 requests/min per user |

### 2.6 curl example

```bash
curl -X POST https://pathzi.co.uk/analytics/activity/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {"activity_type":"career_viewed","career_id":2336,"metadata":{"source":"swipe_deck","position":4}},
      {"activity_type":"career_swiped_right","career_id":2336,"metadata":{"source":"swipe_deck"}}
    ]
  }'
```

### 2.7 Flutter / Dart example

```dart
final res = await http.post(
  Uri.parse('https://pathzi.co.uk/analytics/activity/'),
  headers: {
    'Authorization': 'Bearer $accessToken',
    'Content-Type': 'application/json',
  },
  body: jsonEncode({
    'events': [
      {
        'activity_type': 'career_viewed',
        'career_id': 2336,
        'metadata': {'source': 'swipe_deck', 'position': 4},
      },
    ],
  }),
);
// res.statusCode == 202  ->  {"status": true, "queued": 1}
```

### 2.8 Recommended client pattern (batching)

To save bandwidth and battery, **buffer events on the device and flush in
batches** rather than one request per event:

- Collect events in a local list as the user interacts.
- Flush when the list reaches ~20–50 events, on app background, or every few
  seconds — whichever comes first.
- Keep a batch ≤ 200 events.
- If a flush fails (offline), keep the events and retry on next launch.

---

## 3. `POST /analytics/consent/` — record consent

Records explicit consent for a provider to contact the user. This is the
**only** endpoint that accepts contact data. It is written **synchronously**
(immediately), and also logs an anonymous `consent_given` analytics event
(with no email in it).

### 3.1 Request body

```json
{
  "career_id": 2336,
  "provider_name": "City College",
  "provider_type": "college",
  "contact_email": "user@example.com"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `career_id` | integer | no | Must exist if provided |
| `provider_name` | string | **yes** | Max 255 chars |
| `provider_type` | string | no | e.g. `college`, `employer`, `training_provider` |
| `contact_email` | string | **yes** | Must be a valid email |

### 3.2 Success response — `201 Created`

```json
{
  "status": true,
  "message": "Consent recorded.",
  "lead_id": 17,
  "consent_at": "2026-06-16T13:40:00Z"
}
```

### 3.3 curl example

```bash
curl -X POST https://pathzi.co.uk/analytics/consent/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"career_id":2336,"provider_name":"City College","provider_type":"college","contact_email":"user@example.com"}'
```

---

## 4. Error responses

| Status | Meaning | Example body |
|---|---|---|
| `400 Bad Request` | Validation failed (bad/empty events, disallowed type, >200 events, invalid email) | `{"events": {...}}` or field errors |
| `401 Unauthorized` | Missing/invalid token | `{"detail": "Authentication credentials were not provided."}` |
| `429 Too Many Requests` | Rate limit exceeded (>120/min) | `{"detail": "Request was throttled. Expected available in N seconds."}` |

### 4.1 Common 400 cases (activity endpoint)

- `events` missing or empty → "events must contain at least 1 event."
- More than 200 events → "Too many events …"
- Unknown / backend-only `activity_type` → "Unsupported activity_type '…'. Allowed: […]"
- `metadata` with >50 keys → "metadata has too many keys (max 50)."

> Note: an **invalid or non-existent `career_id` does NOT fail the request**.
> The event is still stored; the broken career link is simply dropped (set to
> null) when written. This keeps high-volume ingest resilient.

---

## 5. Data & privacy rules (GDPR)

- **Never put personal data** (emails, phone numbers, names) in `metadata`.
  The server auto-redacts emails/phone numbers from metadata to `[redacted]`
  as a safety net — but the app should not rely on it.
- Contact data belongs **only** in `POST /analytics/consent/`, and only after
  the user explicitly consents.
- `career_viewed`, `route_clicked`, swipes, etc. are stored as **anonymous**
  analytics.

---

## 6. Behaviour notes (for testers)

- **Asynchronous:** `/analytics/activity/` returns `202` instantly; the event
  appears in the database/reports within **~30 seconds** (a background flush
  runs every 30s). Do not expect it to be queryable the same millisecond.
- **Synchronous:** `/analytics/consent/` writes immediately and returns the
  new `lead_id`.
- **Dependency:** for queued activity events to be persisted, the backend's
  background worker must be running. The consent endpoint does not depend on it.
- **user identity:** events are always attributed to the authenticated user
  from the token, regardless of body content.

---

## 7. QA test checklist

**`/analytics/activity/`**
- [ ] Valid single-event batch → `202`, `queued: 1`; row appears within 30s.
- [ ] Valid 200-event batch → `202`, `queued: 200`.
- [ ] 201 events → `400` (too many).
- [ ] Empty `events: []` → `400`.
- [ ] Missing `events` key → `400`.
- [ ] Disallowed type (`career_saved`) → `400`.
- [ ] Unknown type (`foo_bar`) → `400`.
- [ ] Event with email in metadata → stored with email **redacted**.
- [ ] Non-existent `career_id` → still `202`; row stored without career link.
- [ ] No auth header → `401`.
- [ ] >120 requests in a minute → `429`.

**`/analytics/consent/`**
- [ ] Valid body → `201` with `lead_id` + `consent_at`; ProviderLead row created.
- [ ] Missing `contact_email` → `400`.
- [ ] Invalid email → `400`.
- [ ] Non-existent `career_id` → `400`.
- [ ] Consent event recorded in analytics **without** the email.
- [ ] No auth header → `401`.

---

## 8. Quick reference

```
POST /analytics/activity/   Auth: Bearer   Body: {events:[...]}   -> 202 {queued:N}
POST /analytics/consent/    Auth: Bearer   Body: {provider_name,contact_email,...} -> 201 {lead_id}

Allowed activity_type (activity endpoint):
  career_viewed, career_swiped_right, career_swiped_left,
  route_viewed, route_clicked, provider_link_clicked, connect_button_clicked

Limits: 1–200 events/request · 50 metadata keys/event · 120 requests/min
Events appear in reports within ~30 seconds.
```
