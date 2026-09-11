# careers

The heart of the app: the career catalogue, personalised recommendations, `match_score`,
saving and exploring careers, the courses/jobs/apprenticeships near the user for each career
(with miles), saved pathways (reports), the guest preview list and the progress tracker.

Request/response examples for the recent changes: [API_CHANGES.md](../API_CHANGES.md).

---

## Tables

| Model | Table | Owner | |
|---|---|---|---|
| `CareerJob` (`Career` is a proxy of it) | `fetch_careerjob` | **scraper** (`managed = False`) | One row per career **per label**: 2,415 rows = 745 different careers. `career_type` is `sector` or `category`; `sub_type` is the label (e.g. `Healthcare`). |
| `CareerEmbedding` | `fetch_careerembedding` | **scraper** | 384-number vector + `source_text` per career row |
| `CareerScrapeLog` | `fetch_jobscrapelog` | **scraper** | Scraper run log |
| `UserSavedCareer` | `pathzi_user_saved_career` | this backend | `user_profile`, `career`, `created_at`. The old `report`, `report_status`, `generated_at` columns are **no longer used** (reports moved to the table below). |
| `UserExploredCareer` | `careers_userexploredcareer` | this backend | Careers the user explored |
| `UserCareerReport` | `pathzi_user_career_report` | this backend | Saved pathways: `user_profile`, `career`, `report` (JSON), `report_status`, `generated_at`, `created_at`, `updated_at`; unique per user + career |

Main `fetch_careerjob` fields: `id`, `career_type`, `sub_type`, `normalized_sub_type`, `jobname`,
`job_slug`, `job_url`, `job_description`, `salary`, `hours`, `timings`, `how_to_become`, `college`,
`college_entry_req`, `apprenticeship`, `apprenticeship_entry_req`, `image_url`, `dg_image_url`, `scraped_at`.
In API responses `category` = `sub_type` and `subcategory` = `jobname` (the career title).

---

## Who can call what (`CareerPermission`)

| Access | Actions |
|---|---|
| Anyone | `filter`, `courses`, `jobs`, `apprenticeships`, `list` (guests get `[]`), `retrieve` (guests get `404`) |
| Logged in | `save`, `unsave`, `my`, `explore`, `unexplore`, `explore_mine`, `report`, `reports`, `interactions/bulk` |
| Staff only | create / update / delete careers |

A logged-in user can only open careers in their own chosen categories (`404` otherwise); a user
with no categories can open any career.

---

## Endpoints

| Method | Path | Auth | What it does |
|---|---|---|---|
| GET | `/careers/` | login | Recommendations (ranked) or the fallback list, with `match_score` |
| GET | `/careers/{id}/` | login | Career detail with `my_report`, `is_saved`, `is_explored`, `match_score` |
| POST / GET | `/careers/filter/` | none | Guest preview list |
| GET / POST | `/careers/{id}/courses/` | none | Courses for this career, nearest first, with miles |
| GET / POST | `/careers/{id}/jobs/` | none | Jobs for this career, nearest first, with miles |
| GET / POST | `/careers/{id}/apprenticeships/` | none | Apprenticeships for this career, nearest first, with miles |
| POST | `/careers/{id}/save/` | login | Save a career (`GET` returns the career card) |
| POST | `/careers/{id}/unsave/` | login | Unsave a career |
| POST | `/careers/{id}/explore/` | login | Mark a career explored (`GET` returns the card) |
| POST | `/careers/{id}/unexplore/` | login | Remove explored mark |
| GET | `/careers/my/` | login | Saved careers, with `my_report` and `match_score` |
| GET | `/careers/explore_mine/` | login | Explored careers, with `match_score` |
| POST | `/careers/interactions/bulk/` | login | Save/explore many careers in one call |
| GET / POST / PUT / DELETE | `/careers/{id}/report/` | login | One career's saved pathway (report) |
| GET | `/careers/reports/` | login | All saved pathways, newest first |
| GET | `/me/progress/` | login | Progress tracker |
| POST | `/careers/` | staff | Create (admin) |
| PUT / PATCH / DELETE | `/careers/{id}/` | staff | Edit / delete (admin; only `category` and `subcategory` are writable) |

### Career card (lists)
```json
{ "id": 2418, "category": "Beauty and wellbeing", "subcategory": "Acupuncturist",
  "job_description": "...", "dg_image_url": "https://...", "salary": "Variable", "match_score": 22 }
```
`match_score` is added on `/careers/`, `/careers/{id}/`, `/careers/my/`, `/careers/explore_mine/`
and `/careers/reports/` — not on `/careers/filter/`. `/careers/my/` and `/careers/reports/` items
also have `my_report`.

### `GET /careers/`
- Recommendations ready (cached for 6 hours per user): the recommended careers, ranked, with `match_score`.
- Not ready: every career in the user's categories (or all careers if none), **each career once**,
  ordered by id, and the recommendation pipeline is started in the background. Not ranked.
- Guests: `[]`.

### `POST /careers/filter/` (guest preview)
Body `{"subcategories": ["Healthcare", "Animal care"]}` (category labels; also `?subcategories=` on GET).
Up to 50 random careers per picked category, or 30 per category when nothing is picked; each career
once; categories alternate; a new random order every request. Details: [API_CHANGES.md §3.1](../API_CHANGES.md#31-guest-preview--post-careersfilter-no-login).

### `/careers/{id}/courses|jobs|apprenticeships/`
Sorted nearest first; each item gets `distance_km` and `distance_miles`.

| Param | |
|---|---|
| `lat` + `lng` (or `latitude`/`lon`/`longitude`) | location to sort from |
| `postcode` (or `postal_code`/`zip_code`) | UK postcode, full or district (`M1`) |
| `radius_miles` | default 25, 1–200 |
| `limit`, `offset` | paging, `limit` max 100 |
| `city` | guests only, when no other location is sent |

Location used, first match wins: request `lat`/`lng` → request `postcode` → the user's active saved
location → profile lat/lng → centre of the user's (or guest's) city.
Errors: `400 {"detail": "Postcode not recognised."}`, `400 {"detail": "City is required."}` (guest),
`400 {"detail": "User city not set."}`. Details: [API_CHANGES.md §5](../API_CHANGES.md#5-routes-into-a-career--nearest-first-with-miles).

### Save / unsave / explore / unexplore
| Call | Success | Failure |
|---|---|---|
| `POST /careers/{id}/save/` | `{"status": true, "saved": true}` | `404` unknown career |
| `POST /careers/{id}/unsave/` | `{"status": true, "unsaved": true}` | `404 {"status": false, "message": "Career was not saved."}` |
| `POST /careers/{id}/explore/` | `{"status": true, "explored": true}` | `404` unknown career |
| `POST /careers/{id}/unexplore/` | `{"status": true, "unexplored": true}` | `404 {"status": false, "message": "Career was not explored."}` |

Save/unsave/explore changes clear the user's cached lists and (at most once every 30 seconds)
refresh their recommendations.

### `POST /careers/interactions/bulk/`
```json
{ "items": [ { "career_id": 1, "saved": true }, { "career_id": 2, "explored": true }, { "career_id": 3, "saved": false } ] }
```
At most 100 items; later items for the same career override earlier ones. Rate-limited
(`interaction` scope, 10/second).

Response `200`:
```json
{ "status": true, "updated_count": 3, "saved_changed": 2, "explored_changed": 1 }
```
Errors `400`: `{"status": false, "message": {<validation errors>}}` or
`{"status": false, "message": "Some career IDs are invalid.", "missing_ids": [...]}`.

### Reports (saved pathways)
`/careers/{id}/report/`: `GET` (empty report if none), `POST`/`PUT` body
`{"report": {...}, "report_status": true}`, `DELETE`. `GET /careers/reports/` lists them.
Stored separately from saved careers. Details: [API_CHANGES.md §6](../API_CHANGES.md#6-saved-pathways-reports).

### `GET /me/progress/`
`careers_explored`, `total_careers`, `saved_count`, `category_count`, `streak_days`, `achievements`,
`insight`. Details: [API_CHANGES.md §8](../API_CHANGES.md#8-progress-tracker--get-meprogress).

---

## How recommendations work

1. **Triggers:** `GET /careers/` with no cached list, save/unsave/explore/unexplore, bulk interactions.
   A profile PATCH only clears the cache; the next `GET /careers/` triggers the rebuild.
2. `trigger_recs_debounced` (Redis lock, 60 s) queues the Celery task `update_embedding_and_recs_task`.
3. `accounts/services/user_text_builder.py` writes the user's profile text: education level, age,
   interest categories, up to 5 saved and 5 explored careers.
4. The text is sent to the embedding microservice → 384-number vector → `accounts_userembedding`.
5. pgvector finds the 250 careers (within the user's categories) closest to that vector.
6. Near-duplicates (> 0.95 similar) are dropped → top 50 ids cached for 6 hours (`user_recs:{user_id}`).

**`match_score`** (`services/match_score.py`) = cosine similarity between the user's stored
embedding and the career's, mapped linearly 0.15 → 0 and 0.60 → 100 (calibrated on real users: a
typical best match ≈ 80, median career ≈ 45). `null` when the user has no embedding.

---

## Code map

| File | |
|---|---|
| `views.py` | `CareersView` (all `/careers/` endpoints) |
| `progress_views.py` | `ProgressAPI` (`/me/progress/`) |
| `api/serializers.py` | Card, detail and bulk-interaction serializers |
| `api/permissions.py` | `CareerPermission` |
| `services/nearby_routes.py` | Nearest-first routes, postcode/city centres, distances |
| `services/career_deck.py` | Guest preview list; one-card-per-career fallback |
| `services/match_score.py` | `match_score` |
| `services/progress.py` | Progress tracker numbers |
| `services/recommendation_pipeline.py`, `tasks.py`, `services/recommendation_triggers.py` | Recommendation rebuild (Celery) |
| `services/interactions_bulk.py` | Bulk save/explore |
| `services/embeddings.py`, `services/text_builder.py` | Career-side text and embeddings (used by the scraper) |

---

## Open items

- **Recommendations are frozen until the embedding microservice is restarted** (it is down); new users get `match_score: null` and the unranked fallback list.
- **#24 career pathway**: move pathway generation from the mobile app to the server (and revoke the leaked OpenAI key) — waiting on how the frontend handles it.
- Work style / atmosphere, route options, `training_duration`, `skills[]` — to come from the scraping module (the catalogue tables are managed there).
- Deferred for discussion: provider profile, providers near a location, per-career progress.
- The fallback `GET /careers/` list is not paginated (up to 745 cards).
- Free-tier gating in `views.py` (`FREE_CAREER_LIMIT`, `_is_subscribed`) is written but commented out — part of Part 2 (payments).
- The old report columns on `pathzi_user_saved_career` can be dropped in a later migration.
- Old thread-based recommendation helpers in `accounts/services/` are no longer called and can be removed.
