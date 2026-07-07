"""
Canonical activity type names used across the analytics module.

Always import these constants instead of writing raw strings — this prevents
typos and lets us rename in one place if we ever need to.

Adding a new type is just: add a constant here + add to ACTIVITY_TYPES.
No migration needed because UserActivity.activity_type is a plain CharField.
"""

# ---- Career-card interactions (frontend-fired) ----
CAREER_VIEWED = "career_viewed"
CAREER_SWIPED_RIGHT = "career_swiped_right"
CAREER_SWIPED_LEFT = "career_swiped_left"

# ---- Career search (frontend-fired) ----
# Fired when the user searches for a career. The frontend sends the career_id
# and the searched location (location string in activity_value; optional
# structured detail in metadata).
SEARCHED_CAREER = "searched_career"

# ---- State-changing actions (backend-fired) ----
CAREER_SAVED = "career_saved"
CAREER_UNSAVED = "career_unsaved"
CAREER_EXPLORED = "career_explored"
CAREER_UNEXPLORED = "career_unexplored"

# ---- Education-route interactions (frontend-fired) ----
ROUTE_VIEWED = "route_viewed"
ROUTE_CLICKED = "route_clicked"

# ---- Education-route types (the value carried in UserActivity.route_id for
# route_viewed / route_clicked events). The frontend sends one of these so we
# can report which section of a career a user landed on. ----
ROUTE_COURSE = "course"
ROUTE_APPRENTICESHIP = "apprenticeship"
ROUTE_JOB = "job"
ROUTE_TYPES = (ROUTE_COURSE, ROUTE_APPRENTICESHIP, ROUTE_JOB)

# ---- Provider / lead interactions ----
PROVIDER_LINK_CLICKED = "provider_link_clicked"
CONNECT_BUTTON_CLICKED = "connect_button_clicked"
CONSENT_GIVEN = "consent_given"

# ---- Search ----
SEARCH_PERFORMED = "search_performed"


# Master list — kept in sync with the constants above.
# Used for serializer validation (allowed values) and admin filters.
ACTIVITY_TYPES = (
    CAREER_VIEWED,
    CAREER_SWIPED_RIGHT,
    CAREER_SWIPED_LEFT,
    SEARCHED_CAREER,
    CAREER_SAVED,
    CAREER_UNSAVED,
    CAREER_EXPLORED,
    CAREER_UNEXPLORED,
    ROUTE_VIEWED,
    ROUTE_CLICKED,
    PROVIDER_LINK_CLICKED,
    CONNECT_BUTTON_CLICKED,
    CONSENT_GIVEN,
    SEARCH_PERFORMED,
)

# (value, label) pairs for Django admin display.
# Not enforced at the model layer — kept as a CharField without choices so
# new types can be logged immediately without a migration.
ACTIVITY_TYPE_CHOICES = tuple((t, t.replace("_", " ").title()) for t in ACTIVITY_TYPES)
