# Pathzi — Engineering Documentation

A semantic, AI-assisted **career recommendation platform**. Users provide academic history, interests, future plans, and preferences; the backend builds a semantic profile, runs a vector similarity search against pre-embedded career cards, and returns diversified recommendations. When a user opens a career card, the API surfaces related **jobs**, **courses**, and **apprenticeships** filtered by the user's location.

---

## 1. Stack & Top-Level Layout

| Concern | Technology |
|---|---|
| Web framework | Django 5.2.8 |
| API layer | Django REST Framework 3.16.1 |
| Auth | SimpleJWT + Google OAuth + Apple Sign-In + Session/Basic |
| Database | PostgreSQL (Neon) with **pgvector** extension |
| Cache / locks | Redis (Upstash, TLS) via `django_redis` |
| Embeddings | External ML microservice (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim) |
| Similarity ranking | pgvector cosine distance + `scikit-learn` for diversification |
| Payments | Stripe 14.1.0 (subscription model) |
| Email | SendGrid SMTP (OTP, password reset) |
| Geocoding | Geoapify (autocomplete fallback) |
| Background work | Python `threading.Thread` daemons (Celery is **commented out**) |
| WSGI server | gunicorn |
| Hosting | DigitalOcean App Platform (`stingray-app-jqmc6.ondigitalocean.app`) + Render |

### Directory map

```
pathzi/
├── manage.py
├── requirements.txt
├── .env                           # secrets (DATABASE_URL, REDIS_URL, Stripe, Google, Apple, Geoapify, SendGrid)
├── db.sqlite3                     # legacy / dev only — Postgres is the active DB
├── debug.log                      # rolling INFO log (file handler in settings.LOGGING)
├── categories.json                # canonical category → job-titles map (~200 categories)
├── cities.json                    # city list for a chosen category (generator output)
├── category_counts.py             # one-off: prints per-category job/course/apprenticeship counts
├── extract_cities.py              # one-off: dumps unique cities for a category to cities.json
├── test_autocomplete_performance.py
├── test_nearby_performance.py
├── try.py                         # scratch script — not production
├── neon_backups/                  # SQL backups
│
├── pathzi/                        # project package
│   ├── settings.py
│   ├── urls.py                    # mounts every app under its prefix
│   ├── celery.py                  # placeholder (Celery is not active)
│   ├── wsgi.py / asgi.py
│
├── accounts/                      # auth, user profile, recommendation orchestration
├── qualification/                 # academic history (subjects/grades/year)
├── careers/                       # career cards + recommendations + jobs/courses/apprenticeships fan-out
├── jobs/                          # DWP job vacancies (read-only) + UserSavedJob
├── courses/                       # NCS courses (read-only) + UserSavedCourse
├── apprenticeship/                # Apprenticeship vacancies (read-only) + UserSavedApprenticeship
├── billing/                       # Stripe customer + subscription + webhooks
├── geo_search/                    # location autocomplete + nearby search (DB + Geoapify fallback)
└── usage_limits/                  # CareerSwipeUsage quotas (free vs. paid)
```

### URL mount points (`pathzi/urls.py`)

```
/admin/
/auth/                  → DRF browsable login
/api/billing/           → billing.urls
/accounts/              → accounts.urls
/qualifications/        → qualification.urls
/careers/               → careers.urls
/courses/               → courses.urls
/jobs/                  → jobs.urls
/apprenticeships/       → apprenticeship.urls
/geo/                   → geo_search.urls
/usage-limits/          → usage_limits.urls
```

### Settings highlights (`pathzi/settings.py`)

- `DEBUG = True` and `ALLOWED_HOSTS = ["*"]` — **must be tightened for production**.
- `SECRET_KEY` is the default `django-insecure-…` placeholder — **must be rotated**.
- DRF defaults: SessionAuth, BasicAuth, JWT; global throttle `user: 10/min`.
- SimpleJWT: access **and** refresh tokens both 3 days; rotation disabled.
- Cache: single Redis backend, TLS connection pool (`ssl_cert_reqs: None`).
- DB: `dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=True)`.
- Logging: console + `debug.log` file handler at INFO, root logger.
- Password validators: `CommonPasswordValidator` was deliberately removed (it added 2–3 s to every hash op).

---

## 2. Data Architecture

The system has two clearly separated table families:

### a) **Scraper-owned tables** (read-only, `managed = False`)

Populated by an out-of-band scraping pipeline. The Django models map to them but **do not migrate them**:

| Django model | DB table | Source |
|---|---|---|
| `careers.CareerJob` (alias `Career`) | `fetch_careerjob` | curated UK career profiles |
| `careers.CareerEmbedding` | `fetch_careerembedding` | 384-dim vector per career |
| `jobs.DwpJob` (alias `Job`) | `job_dwpjob` | UK DWP "Find a job" feed |
| `courses.NcsCourse` (alias `Course`) | `course_ncscourse` | National Careers Service |
| `apprenticeship.ApprenticeshipVacancy` | `apprenticeship_apprenticeshipvacancy` | Find an Apprenticeship feed |

Each carries denormalised location columns (`city`, `state`, `zip_code`, `lat`, `lng`) plus a `category`/`subcategory`/`normalized_sub_type` for joins back to careers.

### b) **API-owned tables** (managed by Django migrations)

Everything the user creates: profiles, saves, embeddings, billing, quotas. Crucially, the **save / explore tables store the scraper row's primary key as a plain string/UUID/integer** rather than an FK, so scraper migrations don't break referential integrity.

| Model | Purpose |
|---|---|
| `accounts.UserProfile` | one-to-one with `auth.User`; holds interests, location, etc. |
| `accounts.Coordinates` | multiple saved locations per user (only one `active`) |
| `accounts.UserEmbedding` | 384-dim user vector + source text |
| `accounts.PasswordResetOTP` | 5-minute OTPs for password reset |
| `careers.UserSavedCareer` | (profile, career) join + per-user `report` JSON |
| `careers.UserExploredCareer` | implicit signal: cards the user opened |
| `jobs.UserSavedJob` | (profile, job_id::str) |
| `courses.UserSavedCourse` | (profile, course_id::uuid) |
| `apprenticeship.UserSavedApprenticeship` | (profile, vacancy_ref::str) |
| `qualification.Qualification` | academic records (type, subjects, grades, year) |
| `billing.BillingProfile` | Stripe customer/subscription state |
| `billing.StripeEvent` | webhook idempotency log |
| `usage_limits.CareerSwipeUsage` | swipe counter (free tier cap) |

### pgvector

`careers.CareerEmbedding.embedding` and `accounts.UserEmbedding.embedding` are `pgvector.django.VectorField(dimensions=384)`. Recommendation queries use the `<->` cosine-distance operator via `pgvector.django.CosineDistance` ordering.

---

## 3. The Recommendation Pipeline (end-to-end)

This is the core flow. Read it as: **profile change → text → embedding → vector search → diversify → cache → serve**.

```
PATCH /accounts/user_profile/
        │
        ├── DB write (profile fields, category list, etc.)
        ├── Cache invalidation (user_recs:{user_id})
        └── threading.Thread → update_embedding_and_recs_async(user_id)
                │
                ├── STEP 1 — accounts/services/user_text_builder.py
                │      build_user_career_text(profile)
                │      ⇒ "Career recommendation profile … Education level: A-Level …
                │         Interest categories: Construction, Business …
                │         Strong signals from saved careers: Electrician …"
                │
                ├── STEP 2 — accounts/services/user_embeddings.py
                │      generate_and_store_user_embedding(profile, text)
                │      POST {text} → http://206.189.18.64:8000/ml/embed/
                │      ⇒ 384-dim vector → upsert into accounts_userembedding
                │
                ├── STEP 3 — accounts/services/career_recommender.py
                │      a) get_career_queryset(user, profile)   # filter by user.category
                │      b) retrieve_similar_careers()           # ORDER BY embedding <-> :user_vec LIMIT 50
                │      c) diversify_recommendations()          # drop pairs with cosine sim > 0.95
                │      d) cache.set("user_recs:{uid}", top_ids, 6h)
                │
                └── lock keys in Redis prevent concurrent runs for the same user
```

### Serving recommendations (`GET /careers/`)

`careers/views.py::CareersView.list` reads `user_recs:{uid}` from Redis, hydrates the IDs through the `Career` ORM with `prefetch_related`, joins per-user save/explore status, and returns the page. Misses fall back to a synchronous compute (or empty list, depending on whether the user has an embedding yet).

### Free-tier cap

`FREE_CAREER_LIMIT = 5` is defined in `careers/views.py` but the enforcement block is **currently commented out**. `usage_limits.CareerSwipeUsage` exists and is exposed via `GET /usage-limits/swipe-status/`, but no view actively decrements it on a swipe yet — wire it back before charging.

---

## 4. Career Card → Related Content

When the user opens a card, the frontend hits three independent endpoints. Each does a denormalised filter on the read-only scraper tables. There is **no** join via FK — just `city + jobname`-style equality plus normalisation:

```
GET /careers/<id>/jobs/             → jobs.DwpJob filtered by (city, jobname)
GET /careers/<id>/courses/          → courses.NcsCourse filtered by (city, jobname)
GET /careers/<id>/apprenticeships/  → apprenticeship.ApprenticeshipVacancy filtered by (city, jobname)
```

City comes from the user's **active** `Coordinates` row (or falls back to `UserProfile.city`). Subcategory matching uses `normalized_sub_type` to absorb whitespace/case differences.

Other career endpoints:

```
GET    /careers/                    list (recommendations)
GET    /careers/<id>/               retrieve (full card)
GET    /careers/filter/             ?city=&subcategory=
GET    /careers/my/                 user's saved + explored
POST   /careers/<id>/report/        upsert per-user feedback JSON
```

---

## 5. Apps in Detail

### 5.1 `accounts/` — auth + profile + recommendation orchestration

**Models** (`accounts/models.py`)
- `UserProfile`: `status`, `age`, `education_level`, `discipline`, `city`, `zip_code`, `address`, `category` (JSON list of interests), `report` (JSON list of preference signals), `apple_sub`, legacy `lat/lng`.
- `Coordinates`: multi-location store (`title`, `latitude`, `longitude`, `postal_code`, `state`, `city`, `active`). Saving an `active` row syncs `UserProfile.city` / `lat` / `lng`.
- `PasswordResetOTP`: 6-digit codes, 5-minute TTL.
- `UserEmbedding`: `embedding` (vector 384), `source_text`, `model_name="all-MiniLM-L6-v2"`, `updated_at`.

**Services** (`accounts/services/`)
- `user_text_builder.py` — turns profile + saved/explored careers into a stable English description for embedding. Deduplicates and normalises tokens.
- `user_embeddings.py` — POSTs to the ML microservice with one retry, 2-5 s timeout; persists vector.
- `career_recommender.py` — top-k vector search + `diversify_recommendations()` (sklearn cosine, threshold 0.95) + Redis cache write.
- `recommendation_cache.py` — cache key/TTL helpers.
- `user_service.py` — saved/explored fetchers and `get_career_queryset(user, profile)` which applies the category whitelist.

**Auth endpoints** (`accounts/urls.py`)

| Path | Method | Auth | Notes |
|---|---|---|---|
| `signup/` | POST | Anon | email + password |
| `login/` | POST | Anon | returns JWT pair |
| `user_profile/` | GET / PATCH | JWT | flat shape; PATCH triggers re-embed |
| `user_profile/light/` | GET | JWT | minimal payload for app boot |
| `coordinates/` | GET / POST | JWT | list or create a saved location |
| `coordinates/<id>/` | GET / PATCH / DELETE | JWT | single location |
| `auth/google/` | POST | Anon | Flutter ID-token exchange |
| `auth/apple/` | POST | Anon | Apple ID-token exchange |
| `google/auth/url/` | GET | Anon | web OAuth bootstrap |
| `auth/google/callback/` | GET | Anon | web OAuth callback (test/dev) |
| `forgot_password/` | POST | Anon | email OTP |
| `forgot_password_confirmation/` | POST | Anon | OTP + new password |
| `reset_password/` | POST | JWT | change password while logged in |
| `auth/password/set/request-otp/` | POST | JWT | for social-login users adding a password |
| `auth/password/set/confirm/` | POST | JWT | confirm OTP for above |

JWT lifetimes: 3 days for both access and refresh; rotation off — refresh tokens behave like long-lived bearer tokens.

### 5.2 `careers/`

`careers/api/serializers.py` and `careers/api/permissions.py` hold the DRF wiring. `careers/services/embeddings.py` and `text_builder.py` are the **career-side** mirrors of the user-side helpers (the scraper uses these to build the embedding column).

`CareersView` is a `ModelViewSet` exposing the routes shown in §4 plus `list/retrieve/create/update/destroy` defaults.

### 5.3 `jobs/` / `courses/` / `apprenticeship/`

Each app exposes a CRUD-ish ViewSet over its scraper model and a small set of save/unsave endpoints over its API-owned join table. Filtering is by city + category subset. None of these recompute embeddings — they just hand off rows.

### 5.4 `qualification/`

A simple model storing the user's academic history (qualification type, subjects, grades, completion year) keyed to `UserProfile`. The data feeds back into `user_text_builder` so that "Education level: A-Level — Maths A, Physics A, Chemistry B" can shape the embedding.

### 5.5 `billing/`

- `BillingProfile`: `user` (1-1), `stripe_customer_id`, `stripe_subscription_id`, `plan_id` (`free|monthly|quarterly|yearly`), `subscription_status`, `current_period_end`. Property `is_active` returns `True` only when on a paid plan, status `active`, and the period hasn't elapsed.
- `StripeEvent`: idempotency log for webhook processing.
- `webhooks.py`: handles checkout completion, subscription updates, payment failures.
- `permissions.py`: `IsSubscribed`-style guard reusable from other apps.
- Stripe config in `settings.py`: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_{MONTHLY,QUARTERLY,YEARLY}`, `STRIPE_PLANS` dict.

### 5.6 `geo_search/`

Location autocomplete with a tiered strategy:
1. Heuristic detect: postcode vs. city.
2. Query Postgres for distinct city/postcode values (`db_suggest_distinct`, `db_list_distinct_with_counts`) — returns suggestions plus the count of jobs/courses/apprenticeships at that location.
3. Cache hit/miss in Redis (1-hour TTL).
4. **Fallback**: hit Geoapify when DB is empty for the typed prefix.

Also exposes `search_nearby` for radius-based discovery.

### 5.7 `usage_limits/`

Single model `CareerSwipeUsage(user OneToOne, swipes_used, max_swipes=5)` plus `SwipeStatusView` returning remaining quota. Admins can pass `?user_id=` to inspect another account.

---

## 6. Caching, Concurrency, and Background Work

- **Cache backend**: Redis via `django_redis`. Single connection pool; TLS without strict cert verification (`ssl_cert_reqs: None`).
- **Recommendation cache**: key `user_recs:{user_id}`, TTL 6 h, value = list of career IDs.
- **Autocomplete cache**: per-prefix key in `geo_search`, TTL 1 h.
- **Locks**: `cache.add(lock_key, "1", timeout=…)` is used both for `update_embedding_and_recs_async` and `precompute_recommendations_async` so two concurrent profile patches for the same user don't double-embed.
- **Background execution**: `threading.Thread(target=…, daemon=True).start()`. There is **no Celery / RQ / cron** — the placeholder `pathzi/celery.py` exists but Celery is commented out in `requirements.txt` and `settings.py`. **Implication**: anything scheduled this way is lost on process restart. Migrate to Celery before relying on retries.

---

## 7. External Integrations

| Service | Used by | Notes |
|---|---|---|
| Custom ML embedding API | `accounts.services.user_embeddings` | `POST http://206.189.18.64:8000/ml/embed/`. **Hardcoded raw IP**, no TLS, no retry/backoff beyond a single retry. SPOF. |
| Stripe | `billing/` | subscription mgmt, customer portal, webhooks |
| Google OAuth | `accounts/views.py` | mobile + web flows; verifies via Google JWKS |
| Apple Sign-In | `accounts/views.py` | mobile flow; verifies via Apple JWKS; stores `apple_sub` on UserProfile |
| Geoapify | `geo_search/` | autocomplete fallback when DB has no match |
| SendGrid | `accounts/` (OTP, reset) | SMTP relay configured in settings |

No OpenAI / Anthropic / Hugging Face calls in code — all embedding work is delegated to the self-hosted ML API.

---

## 8. Conventions

- **Class-based views only** (DRF `APIView`, `ViewSet`, `ModelViewSet`).
- Routes registered through DRF routers; custom actions via `@action(detail=True/False, methods=…)`.
- Serializers split into `accounts/serializers.py`, `careers/api/serializers.py`, etc.
- Permissions: `IsAuthenticated` (default for personal data), `AllowAny` (auth bootstrap, OTP), domain-specific guards in `careers/api/permissions.py` and `billing/permissions.py`.
- Logging: every service module pulls `logger = logging.getLogger(__name__)` and emits INFO around external calls and recommendation runs.
- "Read-only scraper, API-owned joins" pattern is consistent across `jobs`, `courses`, `apprenticeship`, and `careers` — follow it for any new content vertical.

---

## 9. Utility Scripts & Generated Data

- `categories.json` — canonical sector → list-of-careers mapping (~200 categories). Source of truth for the user's `category` interest options.
- `cities.json` — output of `extract_cities.py` for one specific category (currently "Construction and trades"). Useful for seeding city pickers.
- `category_counts.py` / `extract_cities.py` — reads `DATABASE_URL`, scans the three scraper tables, and writes counts / city lists.
- `test_autocomplete_performance.py`, `test_nearby_performance.py` — micro-benchmarks for `geo_search`.
- `try.py` — scratch / not used.
- `debug.log` — rolling INFO log; rotate or ship to a log aggregator before scaling.
- `neon_backups/` — manual SQL dumps from Neon.

---

## 10. Known Risks / Tech Debt

| # | Item | Why it matters |
|---|---|---|
| 1 | `DEBUG = True`, `ALLOWED_HOSTS = ["*"]`, default `SECRET_KEY` in `settings.py` | unsafe for the deployed environment |
| 2 | ML embedding service at hardcoded raw IP over HTTP | SPOF, no TLS, no DNS, no retry/backoff beyond one retry |
| 3 | Background work via raw threads | lost on restart; no observability; race-prone despite Redis locks |
| 4 | `FREE_CAREER_LIMIT` enforcement is commented out in `careers/views.py` | free tier is effectively unlimited |
| 5 | No pagination on `GET /careers/` (DRF default page size commented out) | response size grows with recommendation set |
| 6 | Throttle is a global 10/min per user | strict; will bite the swipe UI under normal use |
| 7 | Save/explore tables store FK targets as strings (no DB-level RI) | safer for scraper churn, but orphaned saves go undetected |
| 8 | `db.sqlite3` checked into the repo | left over from `startproject`; should be gitignored |
| 9 | `try.py` and `debug.log` in repo root | scratch / runtime artifacts shouldn't be tracked |
| 10 | JWT refresh lifetime equals access lifetime (3 days), no rotation | re-login every 3 days; no compromise mitigation |

---

## 11. Local Development Quickstart

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. env (.env at repo root)
#    DATABASE_URL=postgres://…?sslmode=require
#    REDIS_URL=rediss://…
#    GOOGLE_WEB_CLIENT_ID, GOOGLE_ANDROID_CLIENT_ID, GOOGLE_IOS_CLIENT_ID,
#    GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
#    APPLE_CLIENT_ID, APPLE_CLIENT_ID_FLUTTER, APPLE_REDIRECT_URI
#    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID_{MONTHLY,QUARTERLY,YEARLY}
#    SENDGRID_API_KEY, DEFAULT_FROM_EMAIL
#    GEOAPIFY_API_KEY, GEOAPIFY_DEFAULT_COUNTRY

# 3. migrate (only API-owned tables — scraper tables are managed=False)
python manage.py migrate

# 4. run
python manage.py runserver 0.0.0.0:8002
```

The scraper tables (`fetch_careerjob`, `fetch_careerembedding`, `job_dwpjob`, `course_ncscourse`, `apprenticeship_apprenticeshipvacancy`) must already exist in the target Postgres database — they are populated by an external pipeline.

---

## 12. Glossary

- **Career card** — a row in `fetch_careerjob`; what the user swipes through.
- **Save / explore** — explicit and implicit user signals; both feed back into the embedding text.
- **Diversification** — sklearn cosine pass that rejects a candidate when it is > 0.95 similar to one already in the result list.
- **Active coordinate** — the single `Coordinates` row a user has marked `active = True`; drives the city filter for jobs/courses/apprenticeships.
- **Embedding text** — a stable English summary of the user, designed to keep the embedding deterministic across runs.
