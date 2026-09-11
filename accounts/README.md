# accounts

Sign-up and login (email/password, Google, Apple), JWT tokens, the user profile, saved locations,
password reset / set-password, and the user embeddings used for recommendations.

Request/response examples for the recent changes (profile, password reset): [API_CHANGES.md](../API_CHANGES.md).

---

## Tables

| Model | Table | |
|---|---|---|
| Django `User` | `auth_user` | username, email, password, first/last name |
| `UserProfile` | `accounts_userprofile` | `appuser` (one-to-one user), `status`, `age`, `education_level`, `discipline`, `user_type`, `city`, `zip_code`, `address`, `category` (list), `qualification` (list), `report_status` + `report` (older profile-level fields), `apple_sub`, `is_apple_private_email`, `lat`, `lng` |
| `Coordinates` | `accounts_coordinates` | Saved locations: `user_profile`, `title`, `latitude`, `longitude`, `postal_code`, `state`, `city`, `active` (one active per user) |
| `PasswordResetOTP` | `accounts_passwordresetotp` | One per user: `otp`, `created_at`, `attempts`, `reset_token_hash`, `reset_token_expires_at`, `reset_token_used_at` |
| `UserEmbedding` | `accounts_userembedding` | One per user: `embedding` (384 numbers, pgvector), `source_text`, `model_name`, `updated_at` |

---

## Endpoints

All under `/accounts/`.

| Method | Path | Auth | |
|---|---|---|---|
| POST | `signup/` | none | Create an account |
| POST | `login/` | none | Email + password login |
| POST | `api/token/` | none | JWT pair from username + password |
| POST | `api/token/refresh/` | none | New access token |
| POST | `auth/google/` | none | Google login from the app |
| POST | `auth/apple/` | none | Apple login from the app |
| GET | `google/auth/url/`, `auth/google/callback/` | none | Browser Google flow (testing) |
| GET / POST | `apple/auth/url/`, `auth/apple/callback/` | none | Browser Apple flow (testing) |
| GET / PATCH / PUT | `user_profile/` | login | The user's profile |
| GET | `user_profile/light/` | login | Small profile for app start-up |
| GET | `users/` | login | All profiles (see open items) |
| GET / POST | `coordinates/` | login | List / add saved locations |
| GET / PATCH / PUT / DELETE | `coordinates/{id}/` | login | One saved location |
| POST | `forgot_password/` | none | Email a reset code |
| POST | `verify_otp/` | none | Check the code → `reset_token` |
| POST | `forgot_password_confirmation/` | none | Set the new password |
| POST | `reset_password/` | login | Change password (knowing the old one) |
| POST | `auth/password/set/request-otp/` | login | Email a code to set a password (social-login users) |
| POST | `auth/password/set/confirm/` | login | Set that password |
| POST | `otp_check/` | login | Check a code (older helper) |

### Sign-up — `POST /accounts/signup/`
```json
{ "username": "alex", "email": "alex@example.com", "password": "N3w-Secure-Pass!", "password2": "N3w-Secure-Pass!" }
```
`201`:
```json
{ "status": true, "message": "User created successfully.",
  "data": { "id": 12, "username": "alex", "email": "alex@example.com",
            "token": { "refresh": "...", "access": "..." } } }
```
`400 {"status": false, "message": ...}` — e.g. `"Username already taken."`, `"Email already registered."`,
or a validation message (passwords at least 8 characters and matching).

### Login — `POST /accounts/login/`
```json
{ "email": "alex@example.com", "password": "..." }
```
`200`:
```json
{ "status": true, "message": "Login successful.", "data": { "token": { "refresh": "...", "access": "..." } } }
```
`400 {"status": false, "message": "Invalid credentials."}`

### Tokens
- `POST /accounts/api/token/` `{"username", "password"}` → `{"refresh", "access"}`
- `POST /accounts/api/token/refresh/` `{"refresh"}` → `{"access"}`
- Access and refresh tokens both last **3 days**; refresh tokens are not rotated.
- Send `Authorization: Bearer <access>`.

### Google — `POST /accounts/auth/google/`
`{"id_token": "<Google ID token from the app>"}`. Creates the account on first login.

`200`:
```json
{ "status": true, "message": "Google login successful",
  "data": { "token": { "refresh": "...", "access": "..." },
            "user": { "id": 12, "username": "...", "email": "...", "name": "...", "first_name": "...", "last_name": "..." } } }
```
`400` messages: `"Missing 'id_token'"`, `"Invalid Google token"`, `"Google verification failed"`,
`"Google token missing email"`, `"Google email is not verified"`. `500 "Login failed, please try again"`.

### Apple — `POST /accounts/auth/apple/`
`{"identity_token": "<Apple identity token>"}`. Stores the Apple user id (`apple_sub`).

`200`: same shape as Google, with `"message": "Apple login successful"`.
`400` messages: `"Missing identity_token"`, `"Invalid Apple token"`, `"Apple email not verified"`,
`"Invalid Apple token data"`. `500 "Login failed, please try again"`.

### Profile — `GET / PATCH /accounts/user_profile/`
Fields: `id`, `status`, `appuser`, `age`, `discipline`, `education_level`, `user_type`, `category`,
`qualification`, `address`, `city`, `zip_code`. Leaving a key out keeps its value; `null` clears it.
Full rules and examples: [API_CHANGES.md §2](../API_CHANGES.md#2-profile--user_type-and-skipped-answers).

A PATCH clears the user's cached recommendations; the next `GET /careers/` rebuilds them.

`GET /accounts/user_profile/light/` → `{"id", "name", "age", "discipline", "education_level"}` (`name` is the username).

### Saved locations — `/accounts/coordinates/`
- `GET` → list of `{"id", "title", "latitude", "longitude", "postal_code", "state", "city", "active"}`
- `POST` `{"title", "latitude", "longitude", "postal_code", "state", "city", "active"}` (`active` defaults to `true`) →
  `201 {"status": true, "message": "Coordinate created successfully.", "data": {...}}`
- `PATCH` / `PUT /accounts/coordinates/{id}/` → `{"status": true, "message": "Coordinate updated successfully.", "data": {...}}`
- `DELETE /accounts/coordinates/{id}/` → `{"status": true, "message": "Coordinate deleted successfully."}`

Rules: an active location makes the user's other locations inactive and copies its city, postcode,
address and lat/lng onto the profile. Deleting the active location makes the most recent remaining
one active. The active location is what `/careers/{id}/courses|jobs|apprenticeships/` sort from.

### Password reset (not logged in)
`forgot_password/` → `verify_otp/` → `forgot_password_confirmation/`: 6-digit code (5 minutes),
single-use `reset_token` (10 minutes), a stable `code` on every error, 5 wrong guesses lock a code,
10 attempts per email and 30 per IP per hour. The old one-step form (code + new password) still works.
Full contract: [API_CHANGES.md §7](../API_CHANGES.md#7-password-reset-otp).

### Change password (logged in) — `POST /accounts/reset_password/`
```json
{ "old_password": "...", "new_password": "...", "new_password2": "..." }
```
`200`:
```json
{ "status": true, "message": "Password changed successfully.", "data": { "token": { "refresh": "...", "access": "..." } } }
```
`400`: `"Old password is incorrect."`, `"New passwords do not match."`, or a validation message.
Also cancels any pending reset code or token.

### Set a password (social-login users, logged in)
- `POST /accounts/auth/password/set/request-otp/` → emails a code;
  `{"status": true, "message": "OTP sent successfully", "code_length": 6, "expires_in": 300}`
- `POST /accounts/auth/password/set/confirm/` `{"otp", "new_password", "confirm_password"}` →
  `{"status": true, "message": "Password reset successful"}`.
  `400`: `"Missing fields"`, `"Passwords does not match."`, `"OTP not requested"`, `"OTP expired"`, `"Incorrect OTP"`.

### `POST /accounts/otp_check/` (logged in, older helper)
`{"otp"}` → `{"status": true, "message": "Correct OTP"}`; `400`: `"OTP required"`, `"OTP not requested"`, `"OTP expired"`, `"Incorrect OTP"`.

---

## Recommendation text and embeddings (`services/`)

| File | |
|---|---|
| `user_text_builder.py` | Writes the text the user's embedding is made from: education level, age, interest categories, up to 5 saved and 5 explored careers. `discipline`, `qualification` and `user_type` are deliberately left out (tested: adding them didn't improve results). |
| `user_embeddings.py` | Sends that text to the embedding microservice and stores the 384-number vector |
| `career_recommender.py` | pgvector search (250 nearest careers) → drop near-duplicates → top 50 → cache for 6 hours |
| `user_service.py` | The career set for a user (their categories, or all) |
| `recommendation_cache.py` | Cache key names |
| `password_reset.py` | Reset codes, attempt limits, single-use reset tokens, error codes |

Rate limits for reset codes/tokens: `throttles.py` (`otp_ip` 30/hour, `otp_email` 10/hour).

## Settings (names only — values are in `.env`)

`SIMPLE_JWT` (lifetimes), `GOOGLE_WEB_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `APPLE_CLIENT_ID`, `APPLE_CLIENT_ID_FLUTTER`,
`APPLE_REDIRECT_URI`, email (SendGrid) settings and `DEFAULT_FROM_EMAIL`.

---

## Open items

- ⚠️ **`GET /accounts/users/` returns every user's full profile to any logged-in user** (address, postcode, coordinates...). Should be staff-only or removed.
- `POST /accounts/forgot_password/` answers `"email does not exist."` for unknown emails, which reveals who has an account (changing it changes what the app shows).
- Refresh tokens last as long as access tokens (3 days) and aren't rotated or blacklisted — needed for "sign out other devices" (deferred).
- `POST /accounts/{pk}/create_qualification` points to a view method that doesn't exist (broken route).
- The embedding microservice is down, so no new embeddings are being made; when it fails, the task errors without a clear message. It needs a restart and a health check.
- `user_type` is stored but not yet used to tailor wording in the app (product decision).
- Unused code that can be removed: `CurrentUserProfileAPI` and `HomeAPI` (not routed), thread-based embedding helpers.
