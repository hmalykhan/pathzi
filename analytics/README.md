# analytics

Records what users do in the app (views, swipes, saves, route and provider clicks, searches),
stores consent to be contacted by providers ("leads"), and powers the staff reports and dashboard.

Detailed docs already in this folder:

| Document | For |
|---|---|
| [API.md](API.md) | `POST /analytics/activity/` and `POST /analytics/consent/` — for the mobile developer and QA |
| [ADMIN.md](ADMIN.md) | Staff report endpoints and what each answers |
| [POSTMAN.md](POSTMAN.md) + [`../Pathzi_Analytics.postman_collection.json`](../Pathzi_Analytics.postman_collection.json) | Ready-made requests |

## Tables

| Model | Table | |
|---|---|---|
| `UserActivity` | `analytics_user_activity` | Append-only event log: `user`, `career`, `route_id` (route type: `course` / `apprenticeship` / `job`), `activity_type`, `activity_value`, `card`, `metadata`, `created_at`. `user` and `career` become `NULL` when deleted, so history survives anonymised. |
| `ProviderLead` | `analytics_provider_lead` | Consent to be contacted: the user, the career, the route item (`route_type` + `route_item_id`), `consented`, contact details (`name`, `contact_email`, `address`, `city`) and item details (`card_name`, `subcategory`, `salary_or_cost`, `provider_name`, `provider_type`), `consent_at`. **Contact data lives only here**, never in `UserActivity`. |

Activity types (`constants.py`): `career_viewed`, `career_swiped_right`, `career_swiped_left`,
`searched_career`, `career_saved`, `career_unsaved`, `career_explored`, `career_unexplored`,
`route_viewed`, `route_clicked`, `provider_link_clicked`, `connect_button_clicked`,
`consent_given`, `search_performed`.

## How events are recorded

- **App events** (`POST /analytics/activity/`, batches of events): pushed onto a Redis list and
  written to the database in bulk by the Celery beat task `flush_activity_queue` **every 30 seconds**.
  Emails and phone numbers are removed from `metadata`.
- **Backend events** (saves, explores...): `log_activity()` queues a Celery task. It never raises,
  so analytics can't break a user's request.
- **Retention:** `purge_old_activity` runs **daily at 03:00** and deletes events older than
  `ANALYTICS_RETENTION_DAYS` (365).

Celery must run with beat: `celery -A pathzi worker -B`.

## Endpoints

### For the app (login required)

| Method | Path | |
|---|---|---|
| POST | `/analytics/activity/` | Report a batch of events (rate limit `analytics`: 120/minute). See [API.md](API.md). |
| POST | `/analytics/consent/` | Record consent to be contacted about a course / job / apprenticeship. See [API.md](API.md). |
| GET | `/analytics/connections/` | The user's consented connections |

`GET /analytics/connections/` response:
```json
{ "status": true, "count": 1, "results": [ {
  "consent_id": 12, "name": "...", "email": "...", "address": "...", "city": "...",
  "route_type": "course", "route_item_id": 61045, "card_name": "...", "subcategory": "...",
  "salary_or_cost": "...", "provider_name": "...", "provider_type": "...",
  "consented": true, "consent_at": "2026-07-20T10:00:00Z" } ] }
```

### Staff reports (`is_staff` only) — all `GET /analytics/admin/...`

| Group | Paths |
|---|---|
| Overview & trends | `overview/`, `timeseries/`, `events/` |
| Careers | `top/<activity_type>/`, `careers/`, `career/<id>/`, `career-users/<activity_type>/`, `career-users/<activity_type>/<career_id>/` |
| Swipes | `like-vs-skip/`, `swipe-users/<career_id>/`, `swipe-careers/`, `swipe-direction/<direction>/` |
| Routes | `routes/`, `routes-by-career/`, `route-users/<career_id>/`, `route-careers/` |
| Providers | `providers/`, `provider-cards/`, `card-users/`, `provider-card-users/` |
| Consent leads | `consent-leads/`, `lead-users/<career_id>/`, `lead-careers/` |
| Searches & places | `searched-careers/`, `searched-career-users/`, `searched-career-groups/`, `by-location/`, `city-users/`, `location-users/` |
| Users | `users/`, `user/<id>/` |
| Data warehouse | `warehouse/<dataset>/`, `warehouse/<dataset>/cities/`, `warehouse/<dataset>/<id>/` (`dataset` = `courses` / `apprenticeships` / `jobs`) |

Most take `?days=`, `?date_from=`, `?date_to=` and/or `?limit=`. Details: [ADMIN.md](ADMIN.md).

### Dashboard

`/dashboard/` (also `/`) — staff-only HTML dashboard; log in at `/login/`.

## Code map

| File | |
|---|---|
| `views.py` | Ingest, consent, connections, report endpoints, dashboard |
| `reports.py` | Report queries |
| `services.py` | `log_activity()`, Redis queue, metadata scrubbing |
| `tasks.py` | Celery tasks (record, flush, purge) |
| `warehouse.py` | Staff browser over the catalogue tables |
| `constants.py` | Activity types |
| `throttles.py`, `permissions.py`, `serializers.py`, `forms.py` | |

## Open items

- The app now sends one `route_viewed` per section (about 3× the old volume). Route charts use `route_clicked` and are unaffected; the per-career drill-down (`career/<id>/`) combines viewed + clicked and will show the jump.
- `route_viewed` events hadn't reached the backup database yet at the time of writing — worth checking once the new app build is live.
