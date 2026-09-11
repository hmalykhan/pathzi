# jobs

UK job vacancies (from the DWP "Find a job" service), collected by the scraping module, plus the
user's saved jobs.

The app mainly shows jobs through **`/careers/{id}/jobs/`** (jobs for one career, nearest first,
with miles) — see [careers](../careers/README.md). This module's own endpoints are the raw
catalogue and saving.

## Tables

| Model | Table | Owner | |
|---|---|---|---|
| `DwpJob` (`Job` is a proxy) | `job_dwpjob` | **scraper** (`managed = False`) | ~41,000 vacancies |
| `JobScrapeLog` | `job_jobscrapelog` | **scraper** | Scraper run log |
| `UserSavedJob` | `pathzi_user_saved_job` | this backend | `user_profile` + `job_id` (the scraper's job id, stored as text — no foreign key, so scraper re-runs don't break saves) |

Main job fields: `id`, `job_id`, `title`, `company`, `salary`, `additional_salary_information`,
`location`, `city`, `state`, `zip_code`, `latitude`, `longitude`, `job_type`, `hours`,
`remote_working`, `posting_date`, `closing_date`, `category`, `subcategory` (= career title),
`listing_snippet`, `summary_intro`, `summary_bullets`, `what_youll_do`, `skills_youll_need`,
`requirement_summery`, `job_url`, `apply_url`, `image_url`, scrape status fields.

API responses add three aliases: `job_name` (= `title`), `status` (= `last_scrape_status`),
`duration` (= `hours`) — plus `user_profile` (see open items).

## Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/jobs/` | login | Every job (not paginated) |
| GET | `/jobs/{id}/` | login | One job |
| GET | `/jobs/my/` | login | The user's saved jobs |
| POST | `/jobs/{id}/save/` | login | `200` — the job object (`GET` also returns it) |
| POST | `/jobs/{id}/unsave/` | login | `200 {"message": "Job unsaved."}` or `404 {"error": "Job was not saved."}` |
| POST | `/jobs/` | staff | Create |
| PUT / PATCH / DELETE | `/jobs/{id}/` | staff | Edit / delete. Staff can edit `city`, `state`, `zip_code`, `latitude`, `longitude`, `category`, `subcategory`. |

Permission class: `JobPermission` (`jobs/api/permissions.py`).

## Open items

- ⚠️ **Privacy:** each job includes `user_profile` — the **full profiles of every user who saved it** (address, postcode, coordinates, username...). This is visible to other users and, via `/careers/{id}/jobs/`, to guests. It should be hidden from non-staff.
- `GET /jobs/` returns the whole table in one response (no paging); the app should use `/careers/{id}/jobs/` or `/geo/nearby/` instead.
- Jobs have no `entry_requirements` field; `requirement_summery` / `skills_youll_need` hold similar text. A consistent field would come from the scraping module.
