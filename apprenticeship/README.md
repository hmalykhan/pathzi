# apprenticeship

Apprenticeship vacancies (from "Find an apprenticeship" and UCAS), collected by the scraping
module, plus the user's saved apprenticeships.

The app mainly shows apprenticeships through **`/careers/{id}/apprenticeships/`** (for one
career, nearest first, with miles) — see [careers](../careers/README.md).

## Tables

| Model | Table | Owner | |
|---|---|---|---|
| `ApprenticeshipVacancy` (`Apprenticeship` is a proxy) | `apprenticeship_apprenticeshipvacancy` | **scraper** (`managed = False`) | ~2,200 vacancies, **almost all in England** |
| `ApprenticeshipScrapeLog` | `apprenticeship_apprenticeshipscrapelog` | **scraper** | Scraper run log |
| `UserSavedApprenticeship` | `pathzi_user_saved_apprenticeship` | this backend | `user_profile` + `vacancy_ref` (text — no foreign key) |

Main fields: `id`, `vacancy_ref`, `vacancy_url`, `title`, `employer_name`, `location_summary`,
`wage`, `wage_extra`, `training_course`, `training_provider`, `hours`, `hours_per_week`,
`start_date`, `duration`, `positions_available`, `summary_text`, `requirement_summery`,
`what_youll_do_items`, `where_youll_work_address`, `what_youll_learn_items`,
`essential_qualifications`, `skills_items`, `other_requirements_items`, `about_employer`,
`employer_website`, `company_benefits_items`, `after_this_apprenticeship`, `closing_text`,
`posted_text`, `city`, `state`, `zip_code`, `latitude`, `longitude`, `category`, `subcategory`
(= career title), `image_url`, scrape status fields. Responses also include `user_profile`.

## Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/apprenticeships/` | login | Every vacancy (not paginated) |
| GET | `/apprenticeships/{id}/` | login | One vacancy |
| GET | `/apprenticeships/my/` | login | The user's saved apprenticeships |
| POST | `/apprenticeships/{id}/save/` | login | `200` — the vacancy object (`GET` also returns it) |
| POST | `/apprenticeships/{id}/unsave/` | login | `200 {"message": "Apprenticeship unsaved."}` or `404 {"error": "Apprenticeship was not saved."}` |
| POST | `/apprenticeships/` | staff | Create |
| PUT / PATCH / DELETE | `/apprenticeships/{id}/` | staff | Edit / delete. Staff can edit `city`, `state`, `zip_code`, `latitude`, `longitude`, `category`, `subcategory`. |

Permission class: `ApprenticeshipPermission` (`apprenticeship/api/permissions.py`).

## Open items

- ⚠️ **Privacy:** each vacancy includes `user_profile` — the **full profiles of every user who saved it**. Visible to other users and, via `/careers/{id}/apprenticeships/`, to guests. It should be hidden from non-staff.
- **Coverage:** 9 vacancies in Scotland, 0 in Wales and Northern Ireland — users outside England will rarely see apprenticeships. A data-source question for the scraping module.
- No single `entry_requirements` field; `essential_qualifications` / `requirement_summery` hold similar text.
