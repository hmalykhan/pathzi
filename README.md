# Pathzi Backend

Django 5.2 + Django REST Framework backend for **Pathzi**, a career-recommendation app for the UK.
Users describe their education, interests and location; the backend recommends careers with
semantic (embedding) search and shows real courses, jobs and apprenticeships near them.

## Modules

Each module has its own README with its tables, every endpoint (request and response), background
work, settings and open items.

| Module | What it does |
|---|---|
| [accounts](accounts/README.md) | Sign-up, login (email, Google, Apple), JWT, profile, saved locations, password reset, user embeddings |
| [careers](careers/README.md) | Career catalogue, recommendations, `match_score`, save/explore, routes (courses/jobs/apprenticeships near the user), saved pathways (reports), guest preview, progress tracker |
| [jobs](jobs/README.md) | DWP job vacancies (read-only catalogue) and saved jobs |
| [courses](courses/README.md) | National Careers Service courses (read-only catalogue) and saved courses |
| [apprenticeship](apprenticeship/README.md) | Apprenticeship vacancies (read-only catalogue) and saved apprenticeships |
| [qualification](qualification/README.md) | Detailed academic records (legacy; the app uses the profile's `qualification` list) |
| [billing](billing/README.md) | Stripe subscriptions, customer portal, webhooks |
| [geo_search](geo_search/README.md) | Location autocomplete, city/postcode lists, nearby search |
| [usage_limits](usage_limits/README.md) | Free-tier swipe counter |
| [analytics](analytics/README.md) | User-activity events, consent leads, staff reports and dashboard |

## Other documents

| Document | For |
|---|---|
| [API_CHANGES.md](API_CHANGES.md) | Latest API changes, with real request/response examples — for the mobile developer and QA |
| [analytics/API.md](analytics/API.md) | Activity and consent endpoints — for the mobile developer |
| [analytics/ADMIN.md](analytics/ADMIN.md) | Staff report endpoints |
| [ENGINEERING.md](ENGINEERING.md) | Architecture overview. Written May 2026; some parts are out of date (Celery is now active, the analytics module and the changes in API_CHANGES.md came later) |

## Conventions

| | |
|---|---|
| Auth | `Authorization: Bearer <access_token>` (JWT). Tokens come from login / sign-up / Google / Apple, or `POST /accounts/api/token/` |
| Format | JSON, `snake_case` |
| Trailing slash | Required on every URL |
| Guests on login-only endpoints | `403 {"detail": "Authentication credentials were not provided."}` |
| Global rate limit | 10 requests/minute per user (DRF `UserRateThrottle`), with higher limits on specific endpoints |

## Data

- **PostgreSQL (Neon) with pgvector.** Two kinds of tables:
  - **Catalogue tables filled by the separate scraping module** (`fetch_careerjob`, `fetch_careerembedding`, `job_dwpjob`, `course_ncscourse`, `apprenticeship_apprenticeshipvacancy`). Django reads them with `managed = False` and never migrates them.
  - **Tables owned by this backend** (profiles, saves, reports, billing, analytics...). Created by Django migrations.
- **Redis** for the cache, rate-limit counters and as the Celery broker.
- **Embedding microservice** (`all-MiniLM-L6-v2`, 384 dimensions) turns user and career text into vectors.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# .env at the repo root needs: DATABASE_URL, REDIS_URL, STRIPE_*, GOOGLE_*, APPLE_*,
# RESEND_API_KEY / email settings, GEOAPIFY_API_KEY  (ask the team for values; never commit them)
python manage.py migrate
python manage.py runserver 0.0.0.0:8002
celery -A pathzi worker -B        # background tasks + periodic tasks (analytics flush/purge)
```

The catalogue tables must already exist in the database (they come from the scraping module).
