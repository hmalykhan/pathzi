# qualification

Detailed academic records — qualification type, subjects, grades, completion year — linked to a
user profile.

**This module is effectively unused.** The table is empty on the backup, and the mobile app sends
qualifications as a simple list on the profile instead (`PATCH /accounts/user_profile/`
`{"qualification": ["Degree", "T-level"]}`, stored in `accounts_userprofile.qualification`).

## Table

`Qualification` → `qualification_qualification`

| Field | Type |
|---|---|
| `id` | integer |
| `qulification_type` | text (field name is misspelled in the database) |
| `subjects` | text |
| `grades` | text |
| `completion_year` | date or null |
| `user_profile` | foreign key to `accounts_userprofile` |

## Endpoints

For the logged-in user's own records:

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/qualifications/add/` | `{"qulification_type", "subjects", "grades", "completion_year"}` | `201 {"Message": "qualification has been added to the <username>", "data": {...}}` |
| GET | `/qualifications/all/` | | `{"data": [ ... ]}` |
| GET | `/qualifications/edit/{id}/` | | `{"data": [ ... ]}` |
| PATCH | `/qualifications/edit/{id}/` | any of the fields | `{"message": "data has been updated", "data": {...}}` |
| GET | `/qualifications/delete/{id}/` | | `{"data": {...}}` |
| DELETE | `/qualifications/delete/{id}/` | | `{"message": "qualification has been deleted"}` |

Errors: `404 {"error": "No qualification found."}`, `404 {"error": "UserProfile not found."}`.

Staff only (`AdminOnlyForCrud`): standard `GET/POST /qualifications/` and
`GET/PUT/PATCH/DELETE /qualifications/{id}/` over all records.

## Open items

- `POST /accounts/{pk}/create_qualification` is routed (in `accounts/urls.py`) to a view method that doesn't exist — the route is broken and should be removed or implemented.
- Decide whether to keep this module or retire it in favour of the profile's `qualification` list.
- Response keys are inconsistent (`Message` vs `message`, a list on `edit` GET).
