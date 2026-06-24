"""
Input validation for the public analytics endpoints.

- ActivityEventSerializer / ActivityBatchSerializer: validate frontend-fired
  events for POST /analytics/activity/ (Lane B — queued, high volume).
- ConsentSerializer: validate POST /analytics/consent/ (synchronous → ProviderLead).
"""

from rest_framework import serializers

from careers.models import Career

from .constants import ACTIVITY_TYPES, ROUTE_TYPES

# Max events accepted in a single /activity/ request (matches the plan).
MAX_EVENTS_PER_BATCH = 200

# Frontend-fired types only. Backend-fired state changes (career_saved etc.)
# are logged server-side in Milestone 3, so we reject them here to stop a
# client from forging them.
FRONTEND_ACTIVITY_TYPES = frozenset(ACTIVITY_TYPES) - frozenset(
    {
        "career_saved",
        "career_unsaved",
        "career_explored",
        "career_unexplored",
        "search_performed",
        "consent_given",  # has its own dedicated endpoint
    }
)


class ActivityEventSerializer(serializers.Serializer):
    activity_type = serializers.CharField(max_length=50)
    career_id = serializers.IntegerField(required=False, allow_null=True)
    # Education-route type for route_viewed / route_clicked events:
    # "course" | "apprenticeship" | "job".
    route_id = serializers.CharField(
        max_length=20, required=False, allow_null=True, allow_blank=True
    )
    activity_value = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False
    )
    # Title of the course/apprenticeship/job card the action refers to.
    card = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    metadata = serializers.DictField(required=False)

    def validate_activity_type(self, value):
        if value not in FRONTEND_ACTIVITY_TYPES:
            raise serializers.ValidationError(
                f"Unsupported activity_type '{value}'. Allowed: "
                f"{sorted(FRONTEND_ACTIVITY_TYPES)}"
            )
        return value

    def validate_route_id(self, value):
        if value in (None, ""):
            return None
        normalized = value.strip().lower()
        if normalized not in ROUTE_TYPES:
            raise serializers.ValidationError(
                f"route_id must be one of {list(ROUTE_TYPES)} (got '{value}')."
            )
        return normalized

    def validate_metadata(self, value):
        # Keep payloads sane; deep PII scrubbing happens in the view via
        # sanitize_metadata(). Here we just bound the size.
        if len(value) > 50:
            raise serializers.ValidationError("metadata has too many keys (max 50).")
        return value


class ActivityBatchSerializer(serializers.Serializer):
    events = ActivityEventSerializer(many=True)

    def validate_events(self, value):
        if not value:
            raise serializers.ValidationError("events must contain at least 1 event.")
        if len(value) > MAX_EVENTS_PER_BATCH:
            raise serializers.ValidationError(
                f"Too many events ({len(value)}). Max {MAX_EVENTS_PER_BATCH} per request."
            )
        return value


class ConsentSerializer(serializers.Serializer):
    career_id = serializers.IntegerField(required=False, allow_null=True)
    provider_name = serializers.CharField(max_length=255)
    provider_type = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    contact_email = serializers.EmailField()

    def validate_career_id(self, value):
        # Synchronous write — a dangling FK would raise, so validate up front.
        if value is not None and not Career.objects.filter(id=value).exists():
            raise serializers.ValidationError(f"Career {value} does not exist.")
        return value
