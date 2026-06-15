# Pathzi Analytics — Admin Reports (handover)

All report endpoints are **staff-only** (`user.is_staff = True`). Send an
admin JWT/session. They are read-only GET endpoints under `/analytics/admin/`.

> Mounted at `/analytics/admin/...` (not `/admin/analytics/`) so they don't
> collide with the Django admin site at `/admin/`.

## Endpoints → what the client asked for

| Dashboard item | Endpoint | Notes |
|---|---|---|
| Total users / views / swipes / right / left | `GET /analytics/admin/overview/?days=30` | one call returns all five totals + saves |
| Most viewed careers | `GET /analytics/admin/top/career_viewed/?limit=20` | |
| Most saved careers | `GET /analytics/admin/top/career_saved/?limit=20` | `top/<any activity_type>/` is generic |
| Like vs skip per career | `GET /analytics/admin/like-vs-skip/` | right, left, like_ratio |
| Most clicked routes | `GET /analytics/admin/routes/` | grouped by route_id |
| Most clicked provider links | `GET /analytics/admin/providers/` | grouped by provider name |
| Careers generating consent leads | `GET /analytics/admin/consent-leads/` | from ProviderLead |
| User activity by date | `GET /analytics/admin/timeseries/?type=&days=30` | for trend charts |
| Popular careers by location | `GET /analytics/admin/by-location/?city=&days=` | see limitation below |
| One career deep-dive | `GET /analytics/admin/career/<id>/` | counts by type + routes + leads |
| One user deep-dive | `GET /analytics/admin/user/<id>/` | counts by type + recent timeline |

Common query params: `?days=N` (time window), `?limit=N` (top-N size).

## Popular-careers-by-location — limitation
Location is read at query time from the user's profile city
(`UserProfile.city`). Events from **deleted/anonymised users have no
location** and are excluded from this report only. (All other reports still
count those rows; just without a user link.) If fuller location coverage is
needed later, have the frontend send `city` in event metadata.

## GDPR
- `career_viewed`, `career_swiped_*`, `route_clicked` etc. are **anonymous**
  analytics — no contact data; emails/phones in metadata are auto-redacted.
- Identifiable contact data lives **only** in `ProviderLead`, written solely
  by the consent endpoint after explicit consent. Never share provider leads
  sourced from anywhere else.
- Retention: `purge_old_activity` (Celery beat, daily 03:00) deletes
  `UserActivity` older than `ANALYTICS_RETENTION_DAYS` (default 365).
  ProviderLead is intentionally NOT auto-purged.

## Operations
- Worker + beat: `celery -A pathzi worker -B --without-mingle --without-gossip --without-heartbeat`
- Enable Redis AOF persistence on Upstash so the Lane B queue survives restarts.
- `celery inspect`/`ping` won't respond (remote control disabled for cost) —
  check the worker's own console output instead.
