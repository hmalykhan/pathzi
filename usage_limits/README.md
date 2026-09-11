# usage_limits

A per-user swipe counter for the free tier: how many career cards a user has swiped and how many
they're allowed.

**Status:** built and working, but **the mobile app doesn't call it at the moment** (swipes are
unlimited in the app, and its constants still point at an old host). It becomes relevant again with
Part 2 (payments/subscriptions).

## Table

`CareerSwipeUsage` → `usage_limits_careerswipeusage`

| Field | |
|---|---|
| `user` | one-to-one with the user |
| `swipes_used` | default 0 |
| `max_swipes` | default 5 |
| `updated_at` | |

A row is created automatically for every new user (signal in `signals.py`).

## Endpoints (login required)

### `GET /usage-limits/swipe-status/`
```json
{ "swipes_used": 2, "max_swipes": 5, "remaining_swipes": 3 }
```
Staff can pass `?user_id=<id>` to see another user (`404 {"detail": "User not found"}`).

### `POST /usage-limits/swipe/`
Records one swipe.
```json
{ "message": "Swipe recorded", "remaining_swipes": 2 }
```
At the limit: `403 {"detail": "Swipe limit reached"}`. Staff can pass `{"user_id": <id>}`.

### `PATCH /usage-limits/update-limit/`
```json
{ "swipes_used": 0, "max_swipes": 10 }
```
Both optional; `max_swipes` can't be lower than `swipes_used`. Returns the swipe-status object.

## Open items

- ⚠️ **`update-limit` is open to every logged-in user** and changes their own counter — so any user can raise their own `max_swipes`. It's labelled "admin" but only checks login. Restrict it to staff (with a `user_id`) before swipe limits are switched back on.
- Tie `max_swipes` to the user's plan (free vs paid) — part of Part 2.
- `careers/views.py` has a second, commented-out limit (`FREE_CAREER_LIMIT = 5`). Use one mechanism, not both.
- Point the app at this backend (`/usage-limits/...`) instead of the old host.
