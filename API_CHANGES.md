# Pathzi Backend — API Changes for the Mobile App

**For:** Flutter developer and QA tester
**Date:** 2026-09-11
**Code:** `main` at `3fc2770` (6 commits on top of `e4b443d dashboard completed.`)
**Covers:** BACKEND.md Part 1 (onboarding) and the Part 3 items built so far

Every example response in this document was captured from the real backend (backup database),
not written by hand. Long text values are shortened with `...`.

---

## Contents

0. [Summary of changes](#0-summary-of-changes)
1. [Conventions](#1-conventions)
2. [Profile — `user_type` and skipped answers](#2-profile--user_type-and-skipped-answers)
3. [Career lists](#3-career-lists)
4. [`match_score`](#4-match_score)
5. [Routes into a career — nearest first, with miles](#5-routes-into-a-career--nearest-first-with-miles)
6. [Saved pathways (reports)](#6-saved-pathways-reports)
7. [Password reset (OTP)](#7-password-reset-otp)
8. [Progress tracker — `GET /me/progress/`](#8-progress-tracker--get-meprogress)
9. [Answers to open questions in BACKEND.md](#9-answers-to-open-questions-in-backendmd)
10. [Tester checklist](#10-tester-checklist)
11. [Known limitations / not in this release](#11-known-limitations--not-in-this-release)

---

## 0. Summary of changes

| # | Area | Endpoint | Type | Breaking for the current app? |
|---|---|---|---|---|
| 1 | Profile | `PATCH/GET /accounts/user_profile/` | New field `user_type` | No |
| 2 | Profile | `PATCH /accounts/user_profile/` | `null` now accepted for skipped answers | No (previously a 400) |
| 3 | Guest preview | `POST/GET /careers/filter/` | Random list, each career once, capped per category | No (same card fields, different order/size) |
| 4 | Career list | `GET /careers/` | Fallback list now shows each career once; new `match_score` | No |
| 5 | Career objects | `/careers/`, `/careers/{id}/`, `/careers/my/`, `/careers/explore_mine/`, `/careers/reports/` | New field `match_score` (last key) | No |
| 6 | Routes | `GET /careers/{id}/courses/`, `/jobs/`, `/apprenticeships/` | Sorted nearest first; new `distance_km`, `distance_miles`; new `lat`/`lng`/`postcode`/`radius_miles` params | No (order changed; more results) |
| 7 | Saved pathways | `/careers/{id}/report/` | Stored separately from saved careers; new `DELETE` | **Behaviour change** — see 6.4 |
| 8 | Saved pathways | `GET /careers/reports/` | **New** list endpoint | No |
| 9 | Password reset | `POST /accounts/forgot_password/` | New fields `code_length`, `expires_in` | No |
| 10 | Password reset | `POST /accounts/verify_otp/` | **New** endpoint, returns `reset_token` | No |
| 11 | Password reset | `POST /accounts/forgot_password_confirmation/` | Accepts `reset_token`; every error has a `code`; rate limits | No — the old `otp` form still works |
| 12 | Progress | `GET /me/progress/` | **New** endpoint | No |

Nothing was removed. Every existing field keeps its name, type and position; new fields are added.

---

## 1. Conventions

| | |
|---|---|
| Base URL | `https://stingray-app-jqmc6.ondigitalocean.app` |
| Auth | `Authorization: Bearer <access_token>` |
| Format | JSON in and out, `snake_case` keys |
| Trailing slash | **Required** on every URL (a POST without it loses its body) |
| PATCH semantics | A key that is left out keeps its stored value. A key sent as `null` clears it. |

**Two existing rules worth knowing while testing** (not new, but easy to mistake for bugs):

- **Guests on a login-only endpoint get `403`, not `401`.** Body: `{"detail": "Authentication credentials were not provided."}`. This is how every login-only endpoint in the project behaves.
- **A logged-in user can only open careers in their own chosen categories.** `GET /careers/{id}/` and `/careers/{id}/courses|jobs|apprenticeships/` return `404 {"detail": "No Career matches the given query."}` for a career outside the user's `category` list. A user with no categories can open any career. Guests get `404` on `GET /careers/{id}/`.

---

## 2. Profile — `user_type` and skipped answers

`PATCH /accounts/user_profile/` and `GET /accounts/user_profile/` — login required.

### 2.1 Fields

| Field | Type | Accepted values | If sent as `null` | If left out |
|---|---|---|---|---|
| `user_type` **(new)** | string or null | `student`, `parent_guardian`, `career_changer`, `reskilling` | stored as `null` | unchanged |
| `education_level` | string | any text; the app's six values all work: `GCSEs`, `A-Levels`, `College`, `University`, `Working`, `Unsure` | stored as `""` | unchanged |
| `category` | list of strings | category display labels, e.g. `"Healthcare"`, `"Computing, technology and digital"` (trimmed, duplicates removed) | stored as `[]` | unchanged |
| `discipline` | string | any text | stored as `""` | unchanged |
| `qualification` | list of strings | e.g. `"T-level"`, `"Apprenticeship"`, `"A-level"`, `"Degree"`, `"Postgrad"` (trimmed, duplicates removed) | stored as `[]` | unchanged |
| `age` | string or null | e.g. `"13-16"`, `"16-18"`, `"18+"` | stored as `null` | unchanged |
| `address`, `zip_code` | string | any text | stored as `""` | unchanged |
| `city` | string or null | any text | stored as `null` | unchanged |

`user_type` labels for the UI:

| Value | Label |
|---|---|
| `student` | Student |
| `parent_guardian` | Parent or Guardian |
| `career_changer` | Career Changer |
| `reskilling` | Reskilling / Upskilling |

`""` for `user_type` is treated like `null`. Any other value is rejected with a `400`.

`id`, `status` and `appuser` (the username) are read-only.

### 2.2 Example — the whole onboarding wizard in one PATCH, with skipped answers

Request:
```http
PATCH /accounts/user_profile/
Authorization: Bearer <token>
Content-Type: application/json

{
  "user_type": "career_changer",
  "education_level": "Working",
  "category": ["Healthcare"],
  "discipline": null,
  "qualification": ["Degree"],
  "zip_code": null
}
```

Response `200` (same shape as `GET /accounts/user_profile/`):
```json
{
  "id": 373,
  "status": false,
  "appuser": "ut_test_d842ec",
  "age": null,
  "discipline": "",
  "education_level": "Working",
  "user_type": "career_changer",
  "category": ["Healthcare"],
  "qualification": ["Degree"],
  "address": "",
  "city": null,
  "zip_code": ""
}
```

### 2.3 Errors

Invalid `user_type` — `400`:
```json
{ "status": false, "message": "\"teacher\" is not a valid choice." }
```
As before, a failed PATCH returns the **first** validation message only, and nothing is saved.

**Before this release**, sending `null` for `discipline`, `education_level`, `address` or `zip_code`
returned `400 "This field may not be null."` and **the whole PATCH was lost** — including every other
answer in it. That no longer happens.

### 2.4 Notes

- `user_type` is stored and returned. It does **not** change recommendations (tested: it didn't improve them). It is there for tailoring wording in the app.
- `qualification` was already saved and returned; confirmed working.

---

## 3. Career lists

All career "cards" in these lists have these fields:

```json
{
  "id": 2696,
  "category": "Creative and media",
  "subcategory": "Public relations officer",
  "job_description": "Public relations (PR) officers manage the public image and reputati...",
  "dg_image_url": "https://pathzi.lon1.cdn.digitaloceanspaces.com/pathzi/career-images...",
  "salary": "£22,000 Starter to £40,000 Experienced"
}
```
(`category` is the category label; `subcategory` is the career title.)

### 3.1 Guest preview — `POST /careers/filter/` (no login)

Also works as `GET /careers/filter/?subcategories=Healthcare&subcategories=Animal%20care`.

Request:
```json
{ "subcategories": ["Healthcare", "Animal care"] }
```
`subcategories` holds **category labels** (the same values as the profile's `category`). Case and spacing don't matter (`"animal care"` works).

| Guest picked | Returns |
|---|---|
| One or more categories | Up to **50 random careers from each** picked category |
| Nothing (`[]` or no key) | **30 random careers from each of the 25 categories** (about 510 cards) |
| A label that doesn't exist | `[]` (as before) |

Rules, both cases:
- **Each career appears once.** (Before: picking nothing returned 2,415 cards with each career ~3 times.)
- **Categories alternate** — card 1 from the first category, card 2 from the next, and so on. When categories are picked, the first cards follow the order they were picked in.
- **The order is different on every request** (random).
- No `match_score` here (guests can't have one).

Response `200` — a list of cards:
```json
[
  { "id": 3028, "category": "Healthcare", "subcategory": "Critical care technologist", "job_description": "...", "dg_image_url": "...", "salary": "£33,706 Starter to £47,672 Experienced" },
  { "id": 2398, "category": "Animal care", "subcategory": "Dog groomer", "job_description": "...", "dg_image_url": "...", "salary": "£15,000 Starter to £23,000 Experienced" }
]
```

### 3.2 Logged-in list — `GET /careers/`

- When the user's recommendations are ready: the recommended careers, **ranked**, as before — now with `match_score`.
- When they aren't ready yet (recommendations are being worked out in the background): every career in the user's categories — or all careers if they have none — **now each career once** (was ~3 times when no categories were chosen), ordered by id. `match_score` is included but this list is **not ranked**, so the scores are not in order.
- Guests: `[]` (unchanged).

```json
[
  { "id": 2418, "category": "Beauty and wellbeing", "subcategory": "Acupuncturist", "job_description": "...", "dg_image_url": "...", "salary": "Variable", "match_score": 22 },
  { "id": 2419, "category": "Beauty and wellbeing", "subcategory": "Aromatherapist", "job_description": "...", "dg_image_url": "...", "salary": "Variable", "match_score": 38 }
]
```

---

## 4. `match_score`

A whole number **0–100**: how well the career fits this user. Added as the **last key** of each career object on:

| Endpoint | |
|---|---|
| `GET /careers/` | each card |
| `GET /careers/{id}/` | the career detail |
| `GET /careers/my/` | each saved career |
| `GET /careers/explore_mine/` | each explored career |
| `GET /careers/reports/` | each saved pathway |

**Not** on `/careers/filter/` (guests) or on course / job / apprenticeship items.

**`null` means there is no score** — the user has no profile embedding yet (for example a brand-new
user), or it's a guest. **Show nothing** in that case; please don't show a placeholder number.
This replaces the client-side `74 + (id % 24)`.

How to read it (measured on real users): a user's best match typically scores about **80**, their
10th-best about **64**, their typical career about **45**, and poor fits under **20**. A few users
will see **100** on their very best match.

The score comes from the same measure the recommendations are ranked by, so on a ranked list it
goes down from the first card. It's the same on the list and on the detail page, and the same on
every request.

Career detail example — `GET /careers/2418/`:
```json
{
  "id": 2418,
  "career_type": "category",
  "category": "Beauty and wellbeing",
  "image_url": "https://res.cloudinary.com/...",
  "dg_image_url": "https://pathzi.lon1.cdn.digitaloceanspaces.com/...",
  "subcategory": "Acupuncturist",
  "job_slug": "acupuncturist",
  "job_url": "https://nationalcareers.service.gov.uk/job-profiles/acupuncturist",
  "job_description": "Acupuncturists insert needles into pressure points on clients' bodi...",
  "salary": "Variable",
  "hours": "37 to 39 variable",
  "timings": "freelance / self-employed managing your own hours",
  "how_to_become": "You can get into this job through specialist courses run by profess...",
  "college": "",
  "college_entry_req": "",
  "apprenticeship_entry_req": "",
  "apprenticeship": "",
  "scraped_at": "2026-01-04T09:07:01.343706Z",
  "my_report": { "report_status": false, "report": {}, "generated_at": null },
  "is_saved": false,
  "is_explored": false,
  "match_score": 22
}
```

---

## 5. Routes into a career — nearest first, with miles

`GET /careers/{career_id}/courses/`
`GET /careers/{career_id}/jobs/`
`GET /careers/{career_id}/apprenticeships/`

Guests and logged-in users. `POST` also works, with the same parameters in a JSON body.

### 5.1 What changed

- **Results are sorted nearest first.**
- **Every item has `distance_km` and `distance_miles`** — the app no longer needs to calculate distances.
- Results come from a **radius** around the location (default 25 miles), not only from the exact same city. So people in a suburb or a nearby town now see results (before, "Admin assistant" courses for Manchester returned **0**; now 38, nearest 2.4 miles away in Salford).

### 5.2 Query parameters

| Parameter | Aliases | Meaning |
|---|---|---|
| `lat` + `lng` | `latitude`, `lon`, `longitude` | Sort from this point. Both needed. |
| `postcode` | `postal_code`, `zip_code` | Sort from this UK postcode. Full (`M1 1AE`), district only (`M1`), lowercase or without a space (`m11ae`) all work. |
| `radius_miles` | | Search radius. Default `25`, min `1`, max `200`. Invalid values fall back to `25`. |
| `limit`, `offset` | | Paging (unchanged). Without `limit` everything within the radius is returned. `limit` max `100`. |
| `city` | | Guests only, when no `lat`/`lng`/`postcode` is sent (unchanged). |

### 5.3 Which location is used (first match wins)

1. `lat` + `lng` sent with the request
2. `postcode` sent with the request
3. the user's active saved location (`/accounts/coordinates/`)
4. the location stored on the profile
5. the centre of the user's city (or of the guest's `city` parameter)

A location sent with the request **overrides** the user's own one.

### 5.4 Response

The same item fields as before (every course / job / apprenticeship field), plus two new ones at the end:

| Field | Type | |
|---|---|---|
| `distance_km` | number or null | 2 decimals |
| `distance_miles` | number or null | 1 decimal |

A distance is `null` only for an item with no coordinates. Those are included only when sorting from
the user's own location and the item is in the user's own city, and they come last.

Example — `GET /careers/2337/courses/?postcode=M1%201AE&limit=2` (fields shortened):
```json
[
  {
    "id": 61045,
    "course_name": "Certificate in Principles of Business Administration (VRQ)",
    "college_name": "FUTURE SKILLS",
    "course_qualification_level": "2",
    "entry_reeq": "Please visit our website for details",
    "cost": "Contact course provider",
    "city": "Salford",
    "zip_code": "M50 2PU",
    "latitude": "53.477006",
    "longitude": "-2.295177",
    "distance_km": 3.85,
    "distance_miles": 2.4
  },
  { "id": 61043, "course_name": "Certificate in Business Administration", "city": "Salford", "distance_km": 3.85, "distance_miles": 2.4 }
]
```

Apprenticeship example — `GET /careers/2337/apprenticeships/?postcode=M1%201AE&radius_miles=50&limit=2` (shortened):
```json
[
  { "id": 39, "title": "Apprentice booking agent assistant", "employer_name": "THREESIXTY ENTERTAINMENT LTD", "wage": "£14,918.80 for your first year, ...", "training_course": "Business administrator (level 3)", "city": "Chadderton", "zip_code": "OL9 9LQ", "distance_km": 9.73, "distance_miles": 6.0 },
  { "id": 1784, "title": "Business Administrator/Admin Assistant apprentice", "employer_name": "SCARSDALE SOLICITORS LTD", "city": "Rochdale", "zip_code": "OL16 1YL", "distance_km": 16.53, "distance_miles": 10.3 }
]
```

### 5.5 Errors

| Case | Status | Body |
|---|---|---|
| Postcode can't be found (e.g. `ZZ9 9ZZ`, `hello`) | `400` | `{"detail": "Postcode not recognised."}` |
| Guest sends no `city`, `lat`/`lng` or `postcode` | `400` | `{"detail": "City is required."}` (unchanged) |
| Logged-in user with no saved location and no city | `400` | `{"detail": "User city not set."}` (unchanged) |
| Logged-in user, career outside their categories | `404` | `{"detail": "No Career matches the given query."}` (unchanged) |

### 5.6 Good to know

- **Apprenticeships are almost only in England** (9 in Scotland, 0 in Wales, 0 in Northern Ireland). A postcode outside England will usually show courses and jobs but no apprenticeships — that is the data, not a bug.
- An empty list is a valid answer when nothing is within the radius (e.g. Edinburgh for "Accounting technician": the nearest course is 41 miles away in Glasgow). Try a larger `radius_miles`.
- `entry_reeq` keeps its current spelling.

---

## 6. Saved pathways (reports)

A report ("saved pathway") is now **stored on its own**, separately from saved careers. Login required.

### 6.1 One career's report — `/careers/{career_id}/report/`

**GET** — Response `200`:
```json
{ "report_status": true, "report": { "score": 82, "summary": "Strong fit" }, "generated_at": "2026-09-11T13:46:16.641219Z" }
```
When there is no report — `200` (**before: `400 "Career is not saved. Save career first."`**):
```json
{ "report_status": false, "report": {}, "generated_at": null }
```

**POST** or **PUT** — create or replace:
```json
{ "report": { "score": 82, "summary": "Strong fit" }, "report_status": true }
```
| Body field | Required | |
|---|---|---|
| `report` | yes | any JSON object |
| `report_status` | no | defaults to `true` |

Response `200`: the saved report, same shape as GET (`generated_at` is set by the server).

**DELETE** (**new** — the trash icon) — Response `200`:
```json
{ "status": true, "deleted": true }
```

### 6.2 All saved pathways — `GET /careers/reports/` (**new**)

Newest first (by last change). Each item is a career card plus `my_report` and `match_score`:
```json
[
  {
    "id": 2418,
    "category": "Beauty and wellbeing",
    "subcategory": "Acupuncturist",
    "job_description": "Acupuncturists insert needles into pressure points on clients' bodi...",
    "dg_image_url": "https://pathzi.lon1.cdn.digitaloceanspaces.com/...",
    "salary": "Variable",
    "my_report": { "report_status": true, "report": { "score": 82, "summary": "Strong fit" }, "generated_at": "2026-09-11T13:46:16.641219Z" },
    "match_score": null
  }
]
```

### 6.3 Errors

| Case | Status | Body |
|---|---|---|
| `report` missing in POST/PUT | `400` | `{"detail": "report is required"}` |
| `career_id` in the body | `400` | `{"detail": "career_id is not allowed in request body."}` |
| `generated_at` in the body | `400` | `{"detail": "generated_at is not allowed in request body."}` |
| Career doesn't exist | `404` | `{"detail": "No Career matches the given query."}` |
| DELETE when there is no report | `404` | `{"status": false, "message": "No report for this career."}` |
| Guest | `403` | `{"detail": "Authentication credentials were not provided."}` |

### 6.4 Behaviour changes — please check the app against these

| Action | Before | Now |
|---|---|---|
| Save a report for a career that isn't saved | Saved the career too | **Only the report is saved** |
| Unsave a career that has a report | Deleted the report too | **The report is kept** |
| GET a report that doesn't exist | `400` | `200` with an empty report |
| Delete only the report | Not possible | `DELETE /careers/{id}/report/` |
| Saving a report changed recommendations | Yes | No (only real career saves do) |

- `my_report` on `GET /careers/{id}/` and on each item of `GET /careers/my/` has the **same shape as before**; it now comes from the separate reports.
- `GET /careers/my/` still lists **saved careers** only. A report without a saved career appears in `GET /careers/reports/`, not in `/careers/my/`.
- All 48 existing reports were copied to the new storage; nothing was lost.

---

## 7. Password reset (OTP)

### 7.1 The new flow

```
Step 1  POST /accounts/forgot_password/          { email }            -> code emailed (6 digits, valid 5 min)
Step 2  POST /accounts/verify_otp/               { email, otp }       -> reset_token (single use, valid 10 min)
Step 3  POST /accounts/forgot_password_confirmation/
                                                 { email, reset_token, new_password, confirm_password }
```
The old one-step form (Step 3 with `otp` instead of `reset_token`) **still works** for current app builds.

No login needed for any of these.

### 7.2 `POST /accounts/forgot_password/`

Request: `{ "email": "alex@example.com" }`

Response `200` (**new fields:** `code_length`, `expires_in` in seconds):
```json
{ "status": true, "message": "OTP sent successfully", "code_length": 6, "expires_in": 300 }
```
Unchanged: missing email -> `400 {"status": false, "message": "Email required"}`;
unknown email -> `200 {"status": false, "message": "email does not exist."}`.

Requesting a new code cancels the previous code, its attempt count and any `reset_token`.

### 7.3 `POST /accounts/verify_otp/` (**new**)

Request:
```json
{ "email": "alex@example.com", "otp": "123456" }
```

Response `200`:
```json
{ "valid": true, "reset_token": "rt_s1WvW6s9AVm_UxBof2wIK6OoeHDU02N0SGnqfTpERiA", "expires_in": 600 }
```
After this the code itself can't be used again — only the token.

Errors (`400` unless shown):
```json
{ "status": false, "code": "otp_invalid", "detail": "Incorrect OTP", "message": "Incorrect OTP", "valid": false }
```
- An **unknown email** gets exactly this same `otp_invalid` answer, on purpose.
- Locked after 5 wrong guesses — `429`:
```json
{ "status": false, "code": "otp_throttled", "detail": "Too many attempts. Please request a new code.", "message": "Too many attempts. Please request a new code.", "retry_after": 0, "valid": false }
```
- Rate limit reached — `429`, with a `Retry-After` header in seconds:
```json
{ "status": false, "code": "otp_throttled", "detail": "Too many attempts. Please try again later.", "message": "Too many attempts. Please try again later.", "retry_after": 3598, "valid": false }
```

### 7.4 `POST /accounts/forgot_password_confirmation/`

**New form** (after `verify_otp`):
```json
{ "email": "alex@example.com", "reset_token": "rt_...", "new_password": "N3w-Secure-Pass!", "confirm_password": "N3w-Secure-Pass!" }
```
**Old form** (still works, same messages as before):
```json
{ "email": "alex@example.com", "otp": "123456", "new_password": "N3w-Secure-Pass!", "confirm_password": "N3w-Secure-Pass!" }
```

Response `200` (unchanged):
```json
{ "status": true, "message": "Password reset successful" }
```

Error example — `400`:
```json
{ "status": false, "code": "password_weak", "detail": "This password is entirely numeric.", "message": "This password is entirely numeric." }
```
Checks run in this order: missing fields -> passwords match -> token/code -> password strength.
A weak password does **not** use up the token: the user can fix the password and try again.

### 7.5 Error codes — every failure has one

Every failure body is `{"status": false, "code": ..., "detail": ..., "message": ...}`. `detail` and
`message` hold the same text. **Please route on `code`, never on the text.**

| `code` | HTTP | `message` | When | What the app should do |
|---|---|---|---|---|
| `missing_fields` | 400 | `Missing fields` | A required field is empty | Show the field error |
| `otp_invalid` | 400 | `Incorrect OTP` (old form, unknown email: `Invalid email`) | Wrong code, unknown email, or code already used | Stay on step 1, clear the boxes |
| `otp_expired` | 400 | `OTP expired` (old form, no code requested: `OTP not requested`) | Code older than 5 minutes | Step 1, offer a resend |
| `otp_throttled` | 429 | `Too many attempts. Please request a new code.` / `Too many attempts. Please try again later.` | 5 wrong guesses, or a rate limit | Show the lockout; use `retry_after` (0 = request a new code now) |
| `token_invalid` | 400 | `Invalid reset token.` | Wrong token, or a newer code was requested | Back to step 1 |
| `token_used` | 400 | `This reset token has already been used.` | Token already used | Back to step 1 |
| `token_expired` | 400 | `Reset token expired. Please verify your code again.` | Token older than 10 minutes | Back to step 1 |
| `password_mismatch` | 400 | `Passwords does not match.` | The two passwords differ | Stay on step 2, field error |
| `password_weak` | 400 | the reason, e.g. `This password is too short. It must contain at least 8 characters.` | Password rejected | Stay on step 2, show `message` |

`password_weak` messages come from the server's password rules: at least 8 characters, not only
digits, not too similar to the username or email. Several reasons are joined into one message.

`verify_otp` failures also include `"valid": false`. `429` responses also include `retry_after` and a `Retry-After` header.

### 7.6 Limits and rules

| Rule | Value |
|---|---|
| Code length | 6 digits |
| Code lifetime | 5 minutes |
| Wrong guesses per code | 5, then the code is locked until a new one is requested |
| Attempts per email | 10 per hour (all `verify_otp` and `forgot_password_confirmation` calls count) |
| Attempts per IP | 30 per hour |
| `reset_token` lifetime | 10 minutes, single use |
| `reset_token` is cancelled by | being used, expiring, a new code being requested, a successful password change |

### 7.7 Changes that also affect current app builds

- **Weak passwords are now rejected on reset** (for example `12345678`). Before, any password was accepted. Current builds will get a `400` with the reason in `message`.
- **Changing the password while logged in** (`POST /accounts/reset_password/`) cancels any pending reset code or token.
- The logged-in "set a password" request (`POST /accounts/auth/password/set/request-otp/`) also returns `code_length` and `expires_in` now. Its confirm step is unchanged.

---

## 8. Progress tracker — `GET /me/progress/`

**New.** Login required (guests get `403`).

Response `200`:
```json
{
  "careers_explored": 24,
  "total_careers": 745,
  "saved_count": 14,
  "category_count": 1,
  "streak_days": 0,
  "achievements": [
    { "key": "first_steps", "unlocked": true, "threshold": 10 },
    { "key": "career_expert", "unlocked": false, "threshold": 50 }
  ],
  "insight": {
    "text": "You've shown strong interest in Administration careers, especially Accounting technician and Bilingual secretary.",
    "highlights": ["Administration", "Accounting technician", "Bilingual secretary"]
  }
}
```

A brand-new user:
```json
{
  "careers_explored": 0,
  "total_careers": 745,
  "saved_count": 0,
  "category_count": 1,
  "streak_days": 0,
  "achievements": [
    { "key": "first_steps", "unlocked": false, "threshold": 10 },
    { "key": "career_expert", "unlocked": false, "threshold": 50 }
  ],
  "insight": null
}
```

| Field | Meaning |
|---|---|
| `careers_explored` | Different careers the user has viewed, swiped (left or right) or explored. Each career counts once. |
| `total_careers` | Different careers in the catalogue — **745**. Use this instead of the hard-coded 770. |
| `saved_count` | Saved careers — the same number as the length of `GET /careers/my/`. |
| `category_count` | Number of interest categories on the profile. |
| `streak_days` | Days in a row with activity, on **UK dates**. Counts up to today, or up to yesterday if there's no activity yet today. 0 if the last activity was 2+ days ago. |
| `achievements` | `unlocked` is `true` when `careers_explored` ≥ `threshold`. |
| `insight` | From the careers the user swiped right on or saved: their top category and their top careers **within** it. `null` until there are at least 3 of those — show nothing then (the old fixed "Tech & Creative" text should go). `highlights` = `[category, career, career]`. |

---

## 9. Answers to open questions in BACKEND.md

| BACKEND.md | Answer |
|---|---|
| 1.2 — six `education_level` values | All six are accepted and returned. |
| 1.3 — skipped answers | `null` / `[]` / missing all accepted (section 2). A user who skips everything still gets careers. |
| 1.5 — does `qualification[]` persist? | Yes, saved and returned. |
| 3.3 — `match_score` | Done (section 4). |
| 3.9 — delete a saved pathway | `DELETE /careers/{id}/report/` (section 6). |
| 3.10 — code length and expiry | 6 digits, 5 minutes; returned as `code_length` / `expires_in`. |
| 3.11 — standalone verify, `reset_token`, error codes, rate limiting | Done (section 7). |
| 3.12 — career image coverage | 99% of careers have `dg_image_url` (2,392 of 2,415 rows). |
| 3.14 — do apprenticeships have `latitude`/`longitude`? | Yes, 99.6%. |
| 3.14 — are route results capped? | No. Everything within the radius is returned; `limit`/`offset` are available (max 100 per page). |
| 3.14 — `entry_reeq` spelling | Unchanged. |
| 3.16 — `distance_km` on career endpoints | Added, plus `distance_miles` (section 5). |
| 3.16 — `route_viewed` volume | Dashboard route charts use `route_clicked`, so the 3× `route_viewed` change doesn't affect them. |
| 3.8 — "770 careers" | The real number is **745**, from `total_careers`. |

---

## 10. Tester checklist

Use two accounts: **A** — has chosen categories and has saved/explored careers; **B** — brand new.

### Profile
- [ ] PATCH `user_type` with each of the 4 values -> 200, GET returns it
- [ ] PATCH `user_type: "teacher"` -> 400 `"\"teacher\" is not a valid choice."`, nothing saved
- [ ] PATCH `user_type: null` and `""` -> stored as `null`
- [ ] PATCH `{"discipline": null, "education_level": null, "category": [], "user_type": null}` in one call -> 200
- [ ] PATCH only `age` -> every other field unchanged
- [ ] Each of the 6 `education_level` values -> 200 and returned

### Guest preview `/careers/filter/`
- [ ] Nothing picked -> about 510 cards, no career twice, no `match_score`
- [ ] Two categories picked -> only those categories, ≤ 50 each, first two cards one from each, no repeats
- [ ] Same request twice -> different order
- [ ] Lowercase label (`"animal care"`) works; unknown label -> `[]`

### Career list and `match_score` (account A)
- [ ] `/careers/`, `/careers/{id}/`, `/careers/my/`, `/careers/explore_mine/`, `/careers/reports/` -> each career has `match_score` 0–100 or null, as the last key
- [ ] Same career -> same score on the list and on the detail page
- [ ] Account B -> `match_score` is `null` everywhere, and the app shows no number
- [ ] Account with no categories -> `/careers/` has no career twice

### Routes
- [ ] Account A, default -> sorted nearest first from the saved location, `distance_miles` on every item
- [ ] `?lat=51.5074&lng=-0.1278` -> London results, nearest first
- [ ] `?postcode=M1 1AE`, `?postcode=m11ae`, `?postcode=M1` -> results near Manchester
- [ ] `?postcode=ZZ9 9ZZ` -> 400 `Postcode not recognised.`
- [ ] Both `lat/lng` and `postcode` sent -> `lat/lng` wins
- [ ] `radius_miles=50` -> more results than the default
- [ ] `limit=2` -> 2 items
- [ ] Guest with no location -> 400 `City is required.`
- [ ] A Scottish or Welsh postcode -> courses/jobs present, apprenticeships usually empty (expected)

### Saved pathways
- [ ] GET a report that doesn't exist -> 200 empty report
- [ ] POST a report for a career that is **not** saved -> 200; the career is still not in `/careers/my/`
- [ ] It appears in `/careers/reports/` (newest first) and in `my_report` on the career detail
- [ ] PUT replaces it
- [ ] Save the career, then unsave it -> the report is still there
- [ ] DELETE -> 200 `{"status": true, "deleted": true}`; DELETE again -> 404
- [ ] POST without `report` -> 400; unknown career id -> 404; guest -> 403

### Password reset
- [ ] forgot_password -> email with a 6-digit code; response has `code_length: 6`, `expires_in: 300`
- [ ] verify_otp with the right code -> `reset_token`, `expires_in: 600`
- [ ] verify_otp with a wrong code -> 400 `otp_invalid`; with an unknown email -> the exact same response
- [ ] The same code a second time after success -> `otp_invalid`
- [ ] 5 wrong codes in a row -> the 5th gives 429 `otp_throttled`; now even the right code gets 429; a new code unlocks it
- [ ] Confirm with the token and `12345678` -> 400 `password_weak`; then a strong password with the **same** token -> 200
- [ ] Log in with the new password -> works; the old password -> fails
- [ ] Same token again -> `token_used`
- [ ] Request a new code, then use the old token -> `token_invalid`
- [ ] Wait 10+ minutes after verify -> `token_expired`
- [ ] Old form (`otp` + passwords) -> still works, messages as before
- [ ] 11 verify attempts for one email within an hour -> the 11th gets 429 with `retry_after` > 0

### Progress
- [ ] Account A -> `saved_count` equals the length of `/careers/my/`; `total_careers` is 745
- [ ] Account B -> zeros, both achievements locked, `insight: null`
- [ ] Swipe right on / save 3+ careers -> `insight` appears, naming a category and careers from it
- [ ] View careers on two days in a row -> `streak_days` 2 (UK dates)
- [ ] Guest -> 403

---

## 11. Known limitations / not in this release

- **Recommendations are frozen for now.** The embedding service is down, so new user profiles aren't turned into embeddings. Until it's restarted, `/careers/` often shows the unranked fallback list, `match_score` reflects each user's last embedding, and new users get `match_score: null`. This does not need an app change.
- **`forgot_password` still says "email does not exist."** for unknown emails, which reveals which emails have accounts. Unchanged for now (it would change what the app shows).
- **Achievements:** only the two from BACKEND.md (`first_steps` 10, `career_expert` 50). If the app shows others, send the keys and thresholds.
- **Not built yet:** Part 2 (payments, trial, referral, entitlements, swipe limits), career pathway on the server (#24), provider profile, providers near a location, `skills[]`, per-career progress, sign out other devices, work style / atmosphere and route options (to come from the scraping module), Swagger docs.
