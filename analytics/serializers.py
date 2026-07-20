"""
Input validation for the public analytics endpoints.

- ActivityEventSerializer / ActivityBatchSerializer: validate frontend-fired
  events for POST /analytics/activity/ (Lane B — queued, high volume).
- ConsentSerializer: validate POST /analytics/consent/ (synchronous → ProviderLead).
"""

from rest_framework import serializers

from apprenticeship.models import Apprenticeship
from courses.models import Course
from jobs.models import Job

from .constants import ACTIVITY_TYPES, ROUTE_TYPES
from .models import ProviderLead

# Maps a route type to the model whose id the lead points at. IDs overlap across
# these tables, so a lead is only resolvable as (route_type, route_item_id).
ROUTE_MODELS = {
    "course": Course,
    "apprenticeship": Apprenticeship,
    "job": Job,
}

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
    """
    The frontend sends ONLY these three fields. Everything else (provider name,
    provider type, contact email) is fetched server-side from the resolved route
    item and the authenticated user.
    """

    # Which route the consent is for (course / apprenticeship / job) + its id.
    route_type = serializers.CharField()
    route_item_id = serializers.IntegerField()
    # Consent flag from the frontend (true = agreed to be contacted). Default false.
    consented = serializers.BooleanField(required=False, default=False)

    def validate_route_type(self, value):
        # Normalise: lowercase, trim, and accept plural spellings (jobs -> job).
        v = (value or "").strip().lower()
        if v.endswith("s"):
            v = v[:-1]
        if v not in ROUTE_MODELS:
            raise serializers.ValidationError(
                f"route_type must be one of {list(ROUTE_MODELS)} (got '{value}')."
            )
        return v

    def validate(self, attrs):
        # Resolve the item in its own table (ids overlap across tables, so we
        # look up only the matching one) and stash it for the view to read
        # provider info from — no extra query needed downstream.
        model = ROUTE_MODELS[attrs["route_type"]]
        obj = model.objects.filter(id=attrs["route_item_id"]).first()
        if obj is None:
            raise serializers.ValidationError(
                {"route_item_id": f"{attrs['route_type']} {attrs['route_item_id']} does not exist."}
            )
        attrs["route_item"] = obj
        return attrs


class ConnectionSerializer(serializers.ModelSerializer):
    """
    Full row of a user's connection (ProviderLead) for GET /analytics/connections/.
    Exposes every stored field so the frontend can render the connected list.
    """

    consent_id = serializers.IntegerField(source="id", read_only=True)
    email = serializers.EmailField(source="contact_email", read_only=True)

    class Meta:
        model = ProviderLead
        fields = [
            "consent_id",
            "name",
            "email",
            "address",
            "city",
            "route_type",
            "route_item_id",
            "card_name",
            "subcategory",
            "salary_or_cost",
            "provider_name",
            "provider_type",
            "consented",
            "consent_at",
        ]
