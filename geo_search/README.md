# geo_search

Location search over the course, job and apprenticeship catalogue: autocomplete for cities and
postcodes, lists of places with counts, and a "near a location" search. No tables of its own.

Its helpers (distance formula, bounding box, city/postcode centres, UK postcode check) are also
used by the careers routes (`careers/services/nearby_routes.py`).

All endpoints require login.

## `types`

Which catalogue(s) to search: `jobs`, `courses`, `apprenticeships` (singular forms and a few common
misspellings are accepted). A list or a comma-separated string. Default: all three.

## Endpoints

### `GET /geo/autocomplete/`

| Param | |
|---|---|
| `text` (or `q`) | what the user typed |
| `types` | see above |
| `limit` | default 8 |

The backend guesses whether the text is a postcode or a city and suggests matching values from
the catalogue. If nothing matches it falls back to Geoapify address search. Results are cached.

Response:
```json
{ "status": true, "kind": "city", "data": [ { "kind": "city", "label": "Manchester", "value": "Manchester" } ] }
```
`kind` is `city`, `postcode`, `address` (Geoapify fallback) or `unknown`. Geoapify items look like:
```json
{ "kind": "address", "place_id": "...", "label": "...", "result_type": "...", "lat": 53.48, "lon": -2.24,
  "city": "Manchester", "state": "England", "postcode": "M1 1AE" }
```
Empty text → `{"status": true, "kind": "unknown", "data": []}`.

### `GET /geo/cities/` and `GET /geo/postcodes/`

| Param | |
|---|---|
| `types` | see above |
| `q` | optional filter |
| `limit` | default 500 |

Response:
```json
{ "status": true, "data": [ { "kind": "city", "value": "Manchester", "count": 1234 } ] }
```
`count` = number of catalogue rows at that place.

### `POST /geo/nearby/`

```json
{
  "types": ["courses", "jobs"],
  "radius_km": 50,
  "location": { "lat": 53.48, "lon": -2.24 },
  "q": "",
  "category": "",
  "subcategory": "Admin assistant",
  "page": 1,
  "page_size": 20
}
```

| Field | |
|---|---|
| `location` | `{"lat", "lon"}`, or `{"city"}`, or `{"postcode"}` / `{"zip_code"}` (city/postcode use the centre of matching catalogue rows) |
| `radius_km` | default 50, 1–200 |
| `q` | free-text filter on title / employer / address |
| `category`, `subcategory` | exact match filters |
| `page`, `page_size` | per type; `page_size` max 100 |

Response:
```json
{
  "status": true,
  "center_source": "db_centroid",
  "center": { "lat": 53.4778, "lon": -2.2371 },
  "radius_km": 50,
  "types": ["courses", "jobs"],
  "results": {
    "courses": { "count": 120, "page": 1, "page_size": 20, "items": [ { "id": 61045, "course_name": "...", "city": "Salford", "latitude": "53.477", "longitude": "-2.295", "distance_km": 3.85 } ] },
    "jobs":    { "count": 46,  "page": 1, "page_size": 20, "items": [ ... ] }
  }
}
```
Items are sorted nearest first with `distance_km`. In items, `job_id` / `course_id` / `vacancy_ref`
hold the database `id`.

Error: `400 {"status": false, "message": "No coordinates found for selected city/postcode in DB."}`

## Code map

| File | |
|---|---|
| `views.py` | The four endpoints |
| `services_db.py` | Distinct values, counts, city/postcode centres, bounding box |
| `services_search.py` | Distance (haversine) SQL and `search_nearby` |
| `services_geoapify.py` | Geoapify fallback |
| `utils.py` | Postcode vs city detection, `UK_POSTCODE_RE` |

Settings: `GEOAPIFY_API_KEY`, `GEOAPIFY_DEFAULT_COUNTRY`.

## Open items

- Guests can't use these endpoints (login required) — worth checking if the app needs location search before sign-up.
- `views.py` contains extra, unrouted copies of the nearby view (dead code).
- City/postcode filters use case-insensitive matches that can't use the indexes on large tables; fine today, may need tuning as data grows.
