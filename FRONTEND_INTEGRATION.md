# Backend changes — integration guide

**For:** mobile developer
**From:** backend
**Date:** 17 September 2026
**Covers:** everything changed since the last hand-over — Parts 1, 2 and 3, plus six security fixes.

Every payload below is **real output from the endpoint**, captured on the backup database.
User details in them are invented; the shapes are not.

---

## Contents

1. [Read this first — breaking changes](#1-read-this-first--breaking-changes)
2. [Career list and detail — new fields](#2-career-list-and-detail--new-fields)
3. [AI career pathway — now server-side](#3-ai-career-pathway--now-server-side)
4. [Routes — distance and relevance](#4-routes--distance-and-relevance)
5. [Access, trial and subscription](#5-access-trial-and-subscription)
6. [Referrals](#6-referrals)
7. [Progress tracker](#7-progress-tracker)
8. [Account deletion](#8-account-deletion)
9. [Sign out other devices](#9-sign-out-other-devices)
10. [Sign-up changes](#10-sign-up-changes)
11. [Profile and onboarding (Part 1)](#11-profile-and-onboarding-part-1)
12. [Password reset — OTP and reset tokens](#12-password-reset--otp-and-reset-tokens)
13. [match_score](#13-match_score)
14. [Analytics — route_viewed](#14-analytics--route_viewed)
15. [Full endpoint list](#15-full-endpoint-list)
16. [Answers to your questions](#16-answers-to-your-questions)
17. [Your work — app side and project side](#17-your-work--app-side-and-project-side)

---

## 1. Read this first — breaking changes

Four things behave differently. Everything else is additive.

### 1.1 `user_profile` is now always `[]`

`GET /careers/{id}/courses|jobs|apprenticeships/` used to return, on every item, the **full
profile of every user who had saved it** — home address, postcode, GPS coordinates, `apple_sub`,
`account_uuid`. With no login required.

It now returns an empty list for everyone except staff.

```json
"user_profile": []
```

**The key is still there**, so nothing crashes if you read it. If you were displaying anything
from it, tell us and we will add a safe replacement (for example a plain saved-count).

### 1.2 Everyone will be signed out once, on deploy

The JWT signing key was rotated (it had been committed to git, so anyone with the repo could
forge a login as any user). **Every existing token becomes invalid the moment this deploys.**

Please make sure the app handles a `401` by sending the user to the login screen rather than
showing an error. It is a one-off.

### 1.3 Changing or resetting a password now ends other sessions

- **Change password while signed in** → other devices are signed out, this one keeps working
  (a fresh token pair comes back in the response, as before).
- **Reset a forgotten password** → *all* sessions end, including this one. The user signs in again.

### 1.4 `forgot_password` no longer says whether the email exists

It used to answer `{"status": false, "message": "email does not exist."}`, which let anyone
check which addresses had an account. Both cases now return **exactly** the same thing:

```json
{ "status": true, "message": "OTP sent successfully", "code_length": 6, "expires_in": 300 }
```

If your UI branched on that message, it needs to stop.

---

## 2. Career list and detail — new fields

### `GET /careers/` — one card

```json
{
  "id": 3010,
  "category": "Healthcare",
  "subcategory": "Acoustics consultant",
  "job_description": "Acoustics consultants work to reduce unwanted noise…",
  "dg_image_url": "https://pathzi.lon1.cdn.digitaloceanspaces.com/…png",
  "salary": "£28,000 Starter to £55,000 Experienced",
  "skills": ["Problem solving", "Analytical", "Attention to detail", "IT skills", "Communication"],
  "work_style": "mixed",
  "work_location": "mixed",
  "work_social": "customer-facing",
  "work_pace": "steady",
  "match_score": null
}
```

**New:** `skills`, `work_style`, `work_location`, `work_social`, `work_pace`.
Everything else is unchanged.

**Allowed values** — fixed lists, so you can safely map them to icons or chips:

| Field | Values |
|---|---|
| `work_style` | `hands-on` · `desk-based` · `mixed` |
| `work_location` | `indoor` · `outdoor` · `mixed` |
| `work_social` | `team` · `independent` · `customer-facing` |
| `work_pace` | `calm` · `steady` · `fast-paced` |

`skills` is 4–6 entries from a fixed vocabulary of 20: Communication, Team working, Organisation,
Attention to detail, Problem solving, Initiative, Patience, Customer care, Logical thinking,
IT skills, Creative, Administrative, Analytical, Number skills, Presentation, Physical fitness,
Non-judgemental, Reliable, Leadership, Time management.

**All four may be `null`** on a career the backfill has not reached. Handle that.

### `GET /careers/{id}/` — detail

Same new fields, plus **`entry_requirements`**, which is one shape across careers, courses, jobs
and apprenticeships so you no longer need four different field names:

```json
"entry_requirements": {
  "college": "Entry requirements for these courses vary.\n- 4 or 5 GCSEs at grades 9 to 4…",
  "apprenticeship": "You'll usually need:\n- some GCSEs, usually including English and maths…",
  "summary": "Entry requirements for these courses vary.\n- 4 or 5 GCSEs at grades 9 to 4…"
}
```

Any of the three may be `null`. `summary` is college, falling back to apprenticeship.

On **courses, jobs and apprenticeships**, `entry_requirements` is a **plain string** (or `null`),
not an object. The original columns (`entry_reeq`, `essential_qualifications`,
`skills_youll_need`, `requirement_summery`) are all still returned — this is an alias, not a
replacement.

---

## 3. AI career pathway — now server-side

**The app must stop calling OpenAI.** Generation happens on our server, and the OpenAI key that
ships inside the app is being revoked.

### `GET /careers/{career_id}/pathway/`

Generates on first request, then returns the stored copy. Roughly **20 seconds** when it
generates, under a second afterwards — please show the existing "Building your personalised
pathway…" state for the first call.

```json
{
  "career_id": 2336,
  "title": "Your Pathway to Becoming an Accounting Technician in Manchester",
  "subtitle": "A comprehensive guide from GCSEs to a qualified Accounting Technician role…",
  "total_timeline_estimate": "6-8 years",
  "current_step": 1,
  "progress": { "current_step": 1, "total_steps": 5, "completed_steps": 0, "percent": 0 },
  "steps": [
    {
      "stepNumber": 1,
      "title": "Complete a T Level in Accounting (2 years), focusing on core accounting principles…",
      "estimatedTime": "",
      "isActive": true,
      "completed": false,
      "current": true
    }
  ],
  "saved": false,
  "generated_at": "2026-09-17T08:22:10Z",
  "generated": true,
  "prompt_version": "2"
}
```

**Notes**

- `progress` is per-career progress, worked out from the profile. **No ticking, no second call.**
  It moves on its own as the user's education level changes.
- Each step carries `completed` and `current`, so you do not have to derive the ticks.
- `saved` is `false` until the user presses Save. The pathway is still stored — that is only a
  cache so we do not pay to generate it twice.
- Always exactly 5 steps and exactly one active step. Guaranteed server-side.
- `generated: true` means it was just built; `false` means it came from storage.

**`?refresh=true`** forces regeneration. Use sparingly — it costs an AI call.

### Saving

```
POST   /careers/{career_id}/pathway/save/    → { "status": true, "career_id": 2336, "saved": true }
DELETE /careers/{career_id}/pathway/save/    → { "status": true, "career_id": 2336, "saved": false }
```

Un-saving hides it from the list but keeps it stored, so re-opening costs nothing.

### When the AI is unavailable

- **User already has a pathway** → `200`, the existing one, plus `"stale": true`.
- **User has none** → `503`:

```json
{ "status": false, "message": "Could not build your pathway just now.", "code": "pathway_unavailable" }
```

Show "Try again" on `pathway_unavailable`.

### Regeneration

Automatic when `age`, `education_level`, `discipline` or `category` change. Changing an address
does **not** regenerate. Saving survives regeneration.

### Do not call `PUT /careers/{id}/report/` after generating

`GET /careers/{id}/pathway/` **already stores the pathway for you**, with `user_saved: false`.
You do not need a second call to persist it.

If you do call `PUT /careers/{id}/report/` as well, it marks the pathway as **saved** unless you
say otherwise — which is why a pathway the user never saved was appearing in their saved list.

The flag is now explicit:

```jsonc
PUT /careers/{id}/report/
{ "report": { … }, "user_saved": false }   // persisted, NOT in the saved list
{ "report": { … } }                        // no flag = the user pressed Save
```

The response echoes it back so you can see what you got.

**Simplest path:** use `GET /pathway/` to generate and `POST /pathway/save/` when the bookmark is
pressed, and never touch the report endpoint.

### The saved list

`GET /careers/reports/` now returns **only pathways the user saved** (`user_saved = true`).
Existing saved pathways were migrated, so nothing is lost. The old
`PUT /careers/{id}/report/` still works and still counts as a deliberate save.

---

## 4. Routes — distance and relevance

`GET /careers/{id}/courses|jobs|apprenticeships/`

### `distance_km` and `distance_miles` are now returned

You no longer need to compute distance on the client. Both are present on every item
(`null` when the row has no coordinates).

### Optional relevance sorting

```
?sort=relevance
```

**Default is unchanged** — nearest first. With `sort=relevance` the list is re-ordered by title
match, then distance, then how complete the record is, and each item gains a `relevance` score
between 0 and 1.

The point: for a carpenter, "Carpentry and Joinery Level 2" eight miles away is a better card
than "Construction (General)" one mile away.

`sort=distance`, no parameter, or an unrecognised value all behave exactly as before.

### Location override

`lat` + `lng`, or `postcode`, override the user's saved location — as before.

---

## 5. Access, trial and subscription

Payments moved from Stripe to **Apple / Google in-app purchase via RevenueCat**.
**Stop calling** `/api/billing/subscribe/` and `/api/billing/portal/`.

The same `access` object is returned inside `GET /api/billing/status/` **and**
`GET /accounts/user_profile/`, so you do not need a second call at start-up:

```json
{
  "has_access": true,
  "source": "trial",
  "access_until": "2026-09-24T08:21:05Z",
  "days_remaining": 7,
  "trial_active": true,
  "trial_days": 7,
  "plan": null,
  "store": null,
  "auto_renewing": false,
  "banked_referral_days": 0,
  "features": ["recommendations", "routes", "reports", "search"],
  "account_uuid": "36b2e5c9-495b-48d3-8860-4624a5dd3a15",
  "manage_url": null
}
```

- `source` — `trial` · `referral` · `subscription` · `none`
- `features` — what the user may use. When access lapses this becomes
  `["explored_careers", "saved", "pathways", "progress", "referrals"]`. **Lock from this list**,
  do not hard-code.
- `account_uuid` — **log into RevenueCat with this**, and pass it to the store as
  `appAccountToken` (iOS) / `obfuscatedAccountId` (Android). It is what ties a purchase to the
  right account.
- `manage_url` — opens the store's own subscription screen. Apple and Google require this.
- `trial_days` — read it, never hard-code 7.

### After a purchase

```
POST /api/billing/refresh/
```

Call it straight after a purchase: it asks RevenueCat directly and returns the same object,
covering the second or two before our webhook lands. If RevenueCat cannot be reached it returns
`refreshed: false` and leaves access unchanged rather than removing it.

### Free tier after the trial

Currently **switched off** server-side, so nothing changes yet. When it is turned on, a user
without access gets only the careers they have already explored or saved from `GET /careers/`.
Saved careers, saved pathways and progress stay available.

---

## 6. Referrals

Every share creates a **new single-use code**. There is no permanent personal code.
First account to use a code consumes it. 30-day expiry. Unlimited codes. You cannot use your own.

```
POST /me/referral/codes/             make a code to share (WhatsApp, etc.)
POST /me/referral/invite             { "email": "..." } — we email a code
GET  /me/referral                    the whole referral screen
POST /me/referral/credits/{id}/ack/  mark the "you earned days" popup as shown
```

### `GET /me/referral`

```json
{
  "status": true,
  "message": "Referral summary.",
  "data": {
    "friends_joined": 0,
    "days_earned": 0,
    "referrer_days": 7,
    "invitee_days": 7,
    "code_expiry_days": 30,
    "invites": [],
    "unseen_credits": []
  }
}
```

### `POST /me/referral/codes/`

```json
{
  "status": true,
  "message": "Referral code created.",
  "data": {
    "id": 92,
    "code": "PTH-HRV8XG",
    "channel": "share",
    "email": null,
    "status": "pending",
    "expires_at": "2026-10-17T08:21:10Z",
    "created_at": "2026-09-17T08:21:10Z"
  }
}
```

`status` per invite is `pending` · `joined` · `expired`.
`unseen_credits` carries `{id, kind, days_awarded, banked, created_at}` — show the popup, then
call the `ack` endpoint so it does not reappear.

**Rewards:** invitee **+7 days** (14 with the trial), referrer **+7**. Days earned while already
subscribed are banked and applied when the subscription ends.

---

## 7. Progress tracker

`GET /me/progress/`

```json
{
  "careers_explored": 0,
  "total_careers": 745,
  "saved_count": 0,
  "category_count": 1,
  "streak_days": 0,
  "achievements": [
    { "key": "first_steps",    "unlocked": false, "threshold": 10 },
    { "key": "career_expert",  "unlocked": false, "threshold": 50 }
  ],
  "insight": null
}
```

**`total_careers` is real (745), not the hard-coded 770.** Read it from here.

**`insight` is `null`** until the user has at least three swipe signals — we would rather show
nothing than invent an insight from one swipe. When present it is
`{"text": "...", "highlights": ["...", "..."]}`.

---

## 8. Account deletion

Apple requires this.

```
DELETE /me/account/          <- use this
DELETE /accounts/me/          <- same thing, still works
```

```json
{
  "status": true,
  "message": "Your account has been deleted. Your subscription is still active — cancel it in the store, or you will keep being charged.",
  "data": {
    "deleted": true,
    "had_active_subscription": true,
    "store": "apple",
    "manage_url": "https://apps.apple.com/account/subscriptions"
  }
}
```

**Deleting the account does not cancel an Apple or Google subscription** — only the store can.
If `had_active_subscription` is `true`, show the message and offer `manage_url` **before**
deleting. Deletion is never blocked because of it.

---

## 9. Sign out other devices

```
POST /accounts/sign-out-other-devices/
```

```json
{
  "status": true,
  "message": "Signed out on all other devices.",
  "data": { "token": { "refresh": "...", "access": "..." } }
}
```

Every other session ends immediately — access and refresh alike. **Use the token pair in the
response**; the one you called with is still valid, but the returned pair is the clean one.

---

## 10. Sign-up changes

All three paths accept an optional `referral_code`:

```
POST /accounts/signup/        { …, "referral_code": "PTH-9QK2TM" }
POST /accounts/auth/google/   { "id_token": "…", "referral_code": "…" }
POST /accounts/auth/apple/    { "identity_token": "…", "referral_code": "…" }
```

Google and Apple responses now include **`is_new_user`** (`true` only when the account was
created), so you can show the trial welcome screen to new accounts only.

All three return a `referral` block:

```json
"referral": { "applied": true, "code": null, "message": "You got 7 bonus days.", "days_awarded": 7 }
```

**A bad code never blocks sign-up.** The account is created and `applied` is `false` with a
reason code: `referral_code_invalid` · `referral_code_used` · `referral_code_expired` ·
`referral_code_own` · `referral_already_credited`.

A 7-day trial now starts automatically on all three paths.

---

## 11. Profile and onboarding (Part 1)

`GET / PATCH /accounts/user_profile/`

**Fields:** `id`, `status`, `appuser`, `age`, `discipline`, `education_level`, `user_type`,
`category`, `qualification`, `address`, `city`, `zip_code` — plus the `access` object
(see [section 5](#5-access-trial-and-subscription)).

### `user_type` — the onboarding persona

"Who is exploring careers today?" Optional, so it may be `null`.

| Value | |
|---|---|
| `student` | Student |
| `parent_guardian` | Parent or Guardian |
| `career_changer` | Career Changer |
| `reskilling` | Reskilling / Upskilling |

Anything outside that list is rejected with `400`.

### Skippable answers

Every onboarding question can be skipped. Two different things:

- **Leave the key out entirely** → the stored value is untouched.
- **Send `null`** → the stored value is cleared.

So a "Skip" button should send `null`, not an empty string. `""` is stored as an empty string
and counts as an answer.

### `education_level`

Free text, six values from the wizard. Stored and returned as sent.

### `qualification`

A list of strings, and it does persist — send the whole list each time, it is replaced not
merged.

```json
PATCH { "user_type": "student", "qualification": ["GCSE Maths", "GCSE English"], "discipline": null }
```

**A PATCH clears the user's cached recommendations**, so the next `GET /careers/` rebuilds them.
It also clears the saved-pathway cache, and any pathway whose inputs changed is regenerated on
next read (see [section 3](#3-ai-career-pathway--now-server-side)).

---

## 12. Password reset — OTP and reset tokens

Three steps. The old one-step form still works, but this is the one to use.

### Step 1 — ask for a code

```
POST /accounts/forgot_password/   { "email": "..." }
```

```json
{ "status": true, "message": "OTP sent successfully", "code_length": 6, "expires_in": 300 }
```

**Read `code_length` and `expires_in`** rather than hard-coding 6 and 5 minutes.

**This response is now identical whether or not the account exists** — see
[section 1.4](#14-forgot_password-no-longer-says-whether-the-email-exists).

### Step 2 — check the code

```
POST /accounts/verify_otp/   { "email": "...", "otp": "123456" }
```

```json
{ "status": true, "reset_token": "…", "expires_in": 600 }
```

The token is **single use** and lasts 10 minutes.

### Step 3 — set the new password

```
POST /accounts/forgot_password_confirmation/
{ "email": "...", "reset_token": "…", "new_password": "...", "confirm_password": "..." }
```

**The field is `confirm_password`, not `new_password2`.** An earlier version of this document
said `new_password2` — that was wrong. `new_password2` belongs to `POST /accounts/reset_password/`,
which is the *logged-in* change-password endpoint, a different thing.

**This ends every session for that user** — see [section 1.3](#13-changing-or-resetting-a-password-now-ends-other-sessions).
The user signs in again with the new password.

### Error codes

Every failure carries a stable `code`, so you can show the right message without parsing English:

| `code` | Meaning |
|---|---|
| `otp_invalid` | wrong code |
| `otp_expired` | older than 5 minutes |
| `otp_throttled` | 5 wrong guesses — the code is dead, request a new one |
| `token_invalid` | reset token not recognised |
| `token_expired` | older than 10 minutes |
| `token_used` | already used once |
| `password_weak` | fails validation — the message says why |
| `password_mismatch` | the two passwords differ |
| `missing_fields` | a required field was not sent |

Each also carries a `message` you can show directly. The wording of the existing ones is
unchanged, because older app builds match on it.

### Limits

10 attempts per email per hour, 30 per IP per hour. Over that returns `429`.

---

## 13. `match_score`

An integer `0–100` on every career object, or **`null`**.

It is the similarity between the user's profile embedding and the career's, mapped so that
0.15 similarity → 0 and 0.60 → 100.

**`null` means we cannot score it yet** — the user has no embedding, which happens before they
have swiped anything, or while the embedding service is rebuilding. **Do not show 0 in that
case**; show nothing, or "not enough data yet". A 0 reads as "terrible match", which is wrong.

It is the last key on `/careers/`, `/careers/{id}/`, `/careers/my/`, `/careers/explore_mine/`
and `/careers/reports/`.

---

## 14. Analytics — `route_viewed`

No API change, but worth knowing: since the app now shows jobs, courses and apprenticeships
together rather than in tabs, it fires **one `route_viewed` per section** instead of one per
tab the user settles on.

**Expect roughly 3× the volume** from that screen, and the three route types to appear in
near-equal proportions rather than `job` dominating because it used to be the default tab.

Any dashboard reading "which route type do users look at?" **will change shape**, and its old
readings were partly an artefact of the tab order. `route_clicked` is unaffected and is the
better signal for genuine interest.

---

## 15. Full endpoint list

**New**

| Method | Path | |
|---|---|---|
| GET | `/me/progress/` | progress tracker (was missing from this list) |
| GET | `/careers/{id}/pathway/` | generate or fetch the pathway |
| POST / DELETE | `/careers/{id}/pathway/save/` | save / unsave |
| POST | `/api/billing/refresh/` | after a purchase |
| POST | `/api/billing/revenuecat/webhook/` | RevenueCat → us (not for the app) |
| GET | `/me/referral` | referral screen |
| POST | `/me/referral/codes/` | new share code |
| POST | `/me/referral/invite` | email an invite |
| POST | `/me/referral/credits/{id}/ack/` | popup shown |
| DELETE | `/me/account/` | delete account (**use this**) |
| DELETE | `/accounts/me/` | same view, kept for compatibility |
| POST | `/accounts/sign-out-other-devices/` | end other sessions |

**Changed**

| Path | Change |
|---|---|
| `GET /careers/` | + skills, work_* |
| `GET /careers/{id}/` | + skills, work_*, entry_requirements |
| `GET /careers/{id}/courses\|jobs\|apprenticeships/` | + distance_km, distance_miles, entry_requirements, `?sort=relevance`; **user_profile now `[]`** |
| `GET /careers/reports/` | only user-saved pathways |
| `GET /api/billing/status/` | + access object |
| `GET /accounts/user_profile/` | + access object |
| `POST /accounts/signup\|auth/google\|auth/apple` | + referral_code, is_new_user, referral block |
| `POST /accounts/forgot_password/` | identical response for unknown emails |
| `GET / PATCH /accounts/user_profile/` | + `user_type`, + access object |
| `POST /accounts/verify_otp/` | single-use `reset_token`, stable error codes |
| `POST /accounts/forgot_password_confirmation/` | takes `reset_token`; ends all sessions |
| `GET /accounts/users/` | staff only |

**Stop calling:** `/api/billing/subscribe/`, `/api/billing/portal/`, and OpenAI directly.

---

## 16. Answers to your questions

### Paths and slashes

**Both forms are registered** for the two that looked wrong, so there is no redirect and no lost
POST body:

```
/me/referral          and  /me/referral/
/me/referral/invite   and  /me/referral/invite/
```

Use the trailing-slash form everywhere. `APPEND_SLASH` is on, so a slashless POST to any *other*
path would 301 and lose its body — those two are covered explicitly because of it.

**Fixed.** Everything about "me" now lives under one prefix:

```
/me/progress/          progress tracker
/me/referral…          referrals
/me/account/           delete account   ← NEW, use this one
/accounts/me/          still works, kept so nothing breaks
```

Both routes reach the same view, so either is correct — but **use `/me/account/`**. The old
`/accounts/me/` stays registered and will not be removed without telling you.

**`GET /me/progress/`** — exact, with the trailing slash. It was missing from §15; fixed.

### Share link

**There is no link.** The `/join` landing page was dropped for v1, so the app shares the **code as
text** — "Use code PTH-HRV8XG" — plus store links if you want them. The invitee types it at
sign-up. No page exists to point at; if you want one, that is a new decision rather than a
missing field.

### Response envelope

**There is a rule, we just had not written it down.** Looking at every endpoint:

> **Endpoints that DO something wrap. Endpoints that RETURN something are bare.**

That holds without exception:

| Wrapped `{status, message, data}` | Bare object |
|---|---|
| `POST /me/referral/codes/` — creates a code | `GET /me/referral` — reads the screen |
| `POST /me/referral/invite` — sends an email | `GET /careers/{id}/pathway/` — reads a pathway |
| `POST/DELETE …/pathway/save/` — changes saved state | `GET /me/progress/` — reads progress |
| `DELETE /me/account/` — deletes the account | the `access` object — read |
| `POST /accounts/sign-out-other-devices/` — ends sessions | career list and detail — read |
| `POST /accounts/signup/` — creates an account | |

The wrapper exists to carry a human-readable `message` about **what just happened**. A read has
nothing to report, so it returns the thing you asked for.

**One exception you should know about:** `GET /me/referral` is a read but wraps anyway, because
it sits in the referral module alongside the writes. If that bothers you, say so — but it is one
endpoint, not a pattern.

We are deliberately **not** standardising the rest. The old endpoints your app already uses
follow the same rule, so changing the new ones would make them differ from the old ones —
trading one inconsistency for a worse one.

### Pathway step fields

**camelCase is deliberate.** `stepNumber` / `isActive` match the shape the app already writes
through `PUT /careers/{id}/report/`, and **48 saved pathways already use it**. Changing it would
break those.

**`progress.current_step` is authoritative.** The other two are conveniences:

| Field | Use it? |
|---|---|
| `progress.current_step` | **yes** |
| `current_step` (top level) | same value, kept for compatibility |
| per-step `current` | same thing, so you can render without a lookup |

All three derive from the single step with `isActive: true`, so they cannot disagree. Three is
still two more than necessary — we kept them for compatibility rather than because it is good.

### Timeouts

**30 seconds server-side.** `?refresh=true` is a full regeneration and takes **the same ~20
seconds** — treat it identically in the UI.

### `features` — the complete list

Only two sets exist:

```
has access : ["recommendations", "routes", "reports", "search"]
no access  : ["explored_careers", "saved", "pathways", "progress", "referrals"]
```

Map each key to a screen. Nothing else will ever appear.

### `banked_referral_days`

**Not** included in `access_until`. They are applied **only when a subscription lapses**.

`access_until` covers the trial, referral days already granted, and the subscription period —
not banked days. So a subscriber showing `banked_referral_days: 7` has 7 days waiting **after**
their subscription ends. Present them as "7 days waiting for you", never as current access.

### Testing the locked state

**Yes.** `PAYWALL_ENFORCED` is an environment variable — set it to `True` on staging and leave it
unset in production. Build and test the free-tier locking there before anyone flips it live.

### Receipts

**Confirmed: no `/api/billing/iap/verify/` exists and none is planned.** The app talks only to
RevenueCat; RevenueCat calls our webhook. You never post a receipt to us.

### Account deletion

`DELETE /accounts/me/` with a valid token is sufficient — **no password or re-auth at the API.**
The confirmation dialog is the app's responsibility. Apple does not require re-auth, but if you
would rather the API demanded a password for something irreversible, say so; it is a small
change and arguably the right one.

---
## 17. Your work — app side and project side

You wear both hats, so this is split by which one you are wearing. Nothing here is optional
for launch unless it says so.

---

### A. App code

#### A1. Must do before this release works at all

| | What | Where in this doc |
|---|---|---|
| ☐ | **Remove the OpenAI key** from the app and call `GET /careers/{id}/pathway/` instead. The key is being revoked — the pathway screen stops working until you switch | [§3](#3-ai-career-pathway--now-server-side) |
| ☐ | **Handle a one-off `401`** on the day this deploys and send the user to login. Every token is invalidated once | [§1.2](#12-everyone-will-be-signed-out-once-on-deploy) |
| ☐ | **Stop calling** `/api/billing/subscribe/` and `/api/billing/portal/` | [§5](#5-access-trial-and-subscription) |
| ☐ | **Check whether you read `user_profile`** on course / job / apprenticeship items. It is now always `[]` | [§1.1](#11-user_profile-is-now-always-) |
| ☐ | **Check whether you call `GET /accounts/users/`** — it now returns `403` | [§15](#15-full-endpoint-list) |
| ☐ | **Stop branching on the `forgot_password` message** — it is now identical for unknown emails | [§1.4](#14-forgot_password-no-longer-says-whether-the-email-exists) |

#### A2. Payments (RevenueCat)

| | |
|---|---|
| ☐ | Log into RevenueCat using **`account_uuid`** from the access object, and pass it to the store as `appAccountToken` (iOS) / `obfuscatedAccountId` (Android). Without this a purchase cannot be matched to an account |
| ☐ | Use **StoreKit 2** (iOS) and **Play Billing 8+** (Android) |
| ☐ | Call **`POST /api/billing/refresh/`** right after a purchase — it covers the second or two before our webhook lands |
| ☐ | Add a **Restore Purchases** button — Apple requires it |
| ☐ | **Manage subscription** opens `manage_url` from the access object, not a page of ours — Apple and Google require this |
| ☐ | **Ask our backend for access** (`/api/billing/status/`), never RevenueCat directly. Trial and referral days only exist with us |

#### A3. Read values from the API, never hard-code

| | Value | Why |
|---|---|---|
| ☐ | `features` | what to lock when the trial ends — do not hard-code the list |
| ☐ | `trial_days` | not 7 |
| ☐ | `total_careers` | it is **745**, not the hard-coded 770 |
| ☐ | `code_length`, `expires_in` | OTP length and lifetime |
| ☐ | `referrer_days`, `invitee_days`, `code_expiry_days` | referral rewards |

#### A4. Null and empty states — easy to get wrong

| | |
|---|---|
| ☐ | **`match_score: null` must not render as 0.** Null = "cannot score yet"; 0 = "terrible match" |
| ☐ | **`insight: null`** until the user has 3+ swipes. Hide the block, do not show empty text |
| ☐ | **`work_style` and `skills` may be `null`** on a career the backfill has not reached |
| ☐ | **Skip must send `null`**, not `""`. Omitting the key leaves the old value; `""` is stored as a real answer |
| ☐ | **Pathway takes ~20 seconds** on first generation. Keep the "Building your personalised pathway…" state; under a second afterwards |
| ☐ | **`503 pathway_unavailable`** → show "Try again". `"stale": true` → show it normally |

#### A5. New screens and flows

| | |
|---|---|
| ☐ | **Referral screen** — a generate-code action *per share* (no permanent code, no "up to 5" limit), the invite list, days earned |
| ☐ | **Referral code field at sign-up**, sent on all three paths |
| ☐ | **`is_new_user`** on Google/Apple — show the trial welcome only to new accounts |
| ☐ | **Delete account** screen (`DELETE /me/account/`) — Apple requires it. If `had_active_subscription` is true, show the warning and `manage_url` **before** deleting |
| ☐ | **Sign out other devices** (`POST /accounts/sign-out-other-devices/`) — use the returned token pair |
| ☐ | **Pathway save/unsave** using `POST`/`DELETE /careers/{id}/pathway/save/` and the `saved` flag |

---

### B. Project side

#### B1. Blocking — no real payment is possible until these are done

Right now the RevenueCat project has **only a Test Store app**. That is a simulator: it cannot
take real money from anyone.

| | |
|---|---|
| ☐ | **App Store Connect**: create the app, then add it in RevenueCat with the In-App Purchase key (`.p8`), Key ID, Issuer ID and bundle ID |
| ☐ | **Play Console**: create the app, then add it in RevenueCat with the service account JSON and package name |
| ☐ | **Banking and tax details** on both. Apple allows no purchase without them, and this is usually the slowest step |
| ☐ | **Create the products** in both stores — monthly and yearly — matching the RevenueCat product IDs, and **send us the final IDs** |
| ☐ | **Delete the "Lifetime" product** unless you intend to sell it. Our database has no lifetime plan, so a purchase would be refused rather than honoured |
| ☐ | **Confirm your RevenueCat account email** — the dashboard banner is still showing |

#### B2. Content we are waiting on

| | |
|---|---|
| ☐ | **Invitation email wording.** Ours is placeholder text. One line to change once you send the real copy |
| ☐ | **Final prices.** The paywall shows £9.99/month and £29/year; confirm against what is configured |

#### B3. Decisions

| | |
|---|---|
| ☐ | **When to switch the free tier on.** It is off (`PAYWALL_ENFORCED=False`) so nothing changes for current users. Turn it on the day the new app ships, or expect people on the old build to lose the home screen |
| ☐ | **Exactly what a free user loses.** Agreed so far: explored and saved careers stay, saved pathways and progress stay, new recommendations stop |

---

### C. First real test, once B1 is done

One test proves the whole payment chain in a way nothing else can:

1. Make a **sandbox purchase** in the app
2. Check our database recorded it (`GET /api/billing/status/` → `source: "subscription"`)

That single test validates the webhook secret matching, the webhook itself, and purchase linking
via `account_uuid`. **None of those three has ever been exercised with a real event** — our tests
prove our logic, not the connection between us and RevenueCat.

---

Anything unclear, ask — it is quicker than guessing from this document.
