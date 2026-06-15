# Pathzi Analytics — Frontend API

Two endpoints for the mobile app to report user activity. Both require
authentication (send the JWT `Authorization: Bearer <token>` header).

> **Golden rule:** never put emails, phone numbers, or names in `metadata`.
> Contact data is only ever sent to `POST /analytics/consent/`. The server
> auto-redacts emails/phones from `metadata` as a safety net, but don't rely
> on it — keep `metadata` to context only.

---

## 1. `POST /analytics/activity/`

Report frontend-fired UI events. Send **1–200 events** per request (batch
them on the client and flush periodically). The server queues them and they
appear in reports within ~30 seconds.

**Request body**

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

**Response** `202 Accepted`

```json
{ "status": true, "queued": 2 }
```

**Notes**
- `user` is taken from your auth token automatically — do **not** send a user id.
- Unknown / disallowed `activity_type` values are rejected (400).
- A bad/old `career_id` doesn't fail the batch — that event is just stored
  without a career link.

### Allowed `activity_type` values + fields

| activity_type            | career_id   | route_id    | activity_value      | suggested metadata keys              |
|--------------------------|-------------|-------------|---------------------|--------------------------------------|
| `career_viewed`          | required    | —           | —                   | `source`, `position`, `session_id`   |
| `career_swiped_right`    | required    | —           | —                   | `source`, `position`, `session_id`   |
| `career_swiped_left`     | required    | —           | —                   | `source`, `position`, `session_id`   |
| `route_viewed`           | required    | required    | route name (opt.)   | `source`                             |
| `route_clicked`          | required    | required    | route name (opt.)   | `source`                             |
| `provider_link_clicked`  | required    | optional    | provider name (opt.)| `provider_type`, `url`               |
| `connect_button_clicked` | required    | optional    | provider name (opt.)| `provider_type`                      |

> These are the only types this endpoint accepts. Backend actions
> (`career_saved`, `career_unsaved`, `career_explored`, `career_unexplored`,
> `search_performed`) are logged server-side automatically — don't send them.
> `consent_given` has its own endpoint below.

**Limits:** up to 200 events/request, up to 50 metadata keys/event,
rate limit 120 requests/min per user.

### curl example

```bash
curl -X POST https://pathzi.co.uk/analytics/activity/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"events":[{"activity_type":"career_viewed","career_id":2336,"metadata":{"source":"swipe_deck","position":4}}]}'
```

---

## 2. `POST /analytics/consent/`

Record explicit consent for a provider to contact the user. This is the
**only** endpoint that accepts contact data. Written immediately (synchronous).

**Request body**

```json
{
  "career_id": 2336,
  "provider_name": "City College",
  "provider_type": "college",
  "contact_email": "user@example.com"
}
```

| field           | required | notes                                |
|-----------------|----------|--------------------------------------|
| `career_id`     | optional | must exist if provided               |
| `provider_name` | required | max 255 chars                        |
| `provider_type` | optional | e.g. `college`, `course_provider`    |
| `contact_email` | required | valid email                          |

**Response** `201 Created`

```json
{
  "status": true,
  "message": "Consent recorded.",
  "lead_id": 17,
  "consent_at": "2026-06-11T13:40:00Z"
}
```

### curl example

```bash
curl -X POST https://pathzi.co.uk/analytics/consent/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"career_id":2336,"provider_name":"City College","provider_type":"college","contact_email":"user@example.com"}'
```
