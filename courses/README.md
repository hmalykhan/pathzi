# courses

Courses from the National Careers Service, collected by the scraping module, plus the user's
saved courses.

The app mainly shows courses through **`/careers/{id}/courses/`** (courses for one career, nearest
first, with miles) — see [careers](../careers/README.md). This module's own endpoints are the raw
catalogue and saving.

## Tables

| Model | Table | Owner | |
|---|---|---|---|
| `NcsCourse` (`Course` is a proxy) | `course_ncscourse` | **scraper** (`managed = False`) | ~105,000 courses, in all four UK nations |
| `CourseScrapeLog` | `course_coursescrapelog` | **scraper** | Scraper run log |
| `UserSavedCourse` | `pathzi_user_saved_course` | this backend | `user_profile` + `course_id` (the scraper's course UUID — no foreign key) |

Main course fields: `id`, `course_id`, `course_name`, `course_type`, `course_qualification_level`,
`learning_method`, `course_hours`, `course_stryd_time` (start), `duration`, `attendance_pattern`,
`awarding_organization`, `who_this_course_is_for`, `entry_reeq` (entry requirements — spelling kept
for the app), `requirement_summery`, `course_description`, `cost`, `cost_description`,
`college_name`, `address`, `city`, `state`, `zip_code`, `latitude`, `longitude`, `email`, `phone`,
`website`, `course_url`, `image_url`, `category`, `subcategory` (= career title), scrape status fields.
Responses also include `user_profile` (see open items).

## Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/courses/` | login | Every course (not paginated) |
| GET | `/courses/{id}/` | login | One course |
| GET | `/courses/my/` | login | The user's saved courses |
| POST | `/courses/{id}/save/` | login | `200` — the course object (`GET` also returns it) |
| POST | `/courses/{id}/unsave/` | login | `200 {"message": "Course unsaved."}` or `404 {"error": "Course was not saved."}` |
| POST | `/courses/` | staff | Create (links an existing scraped course by `course_id`) |
| PUT / PATCH / DELETE | `/courses/{id}/` | staff | Edit / delete. Staff can edit `city`, `state`, `zip_code`, `latitude`, `longitude`, `category`, `subcategory`. |

Permission class: `CoursePermission` (`courses/api/permissions.py`).

## Open items

- ⚠️ **Privacy:** each course includes `user_profile` — the **full profiles of every user who saved it** (address, postcode, coordinates, username...). This is visible to other users and, via `/careers/{id}/courses/`, to guests. Verified on the backup. It should be hidden from non-staff.
- `GET /courses/` returns the whole table (~105k rows) in one response; the app should use `/careers/{id}/courses/` or `/geo/nearby/`.
- `entry_reeq` is a misspelling; if it's ever renamed, ship the new name alongside the old one.
- `CoursePermission` lists a `bulk_interactions` action that this module doesn't have (harmless leftover).
