from django.conf import settings
from django.db import models


class UserActivity(models.Model):
    """
    Append-only event log. One row per user action.

    Designed for high write volume + simple GROUP BY queries.
    All optional fields are nullable so we can log partial events
    (e.g. a search has no career_id, a route click has no career_id).

    `user` and `career` use SET_NULL on delete so analytics history
    is preserved (and anonymised) when those records are removed.
    This is the GDPR-safe pattern.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )

    # Use string ref to avoid importing careers app at module load time.
    # `careers.Career` is a proxy of CareerJob (managed=False) — the FK
    # constraint points at the scraper-owned table.
    career = models.ForeignKey(
        "careers.Career",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )

    # Education-route TYPE the event refers to: "course" | "apprenticeship" |
    # "job" (see constants.ROUTE_TYPES). Kept as the column name `route_id` for
    # backwards compatibility; null for events that aren't route interactions.
    route_id = models.CharField(max_length=20, null=True, blank=True)

    activity_type = models.CharField(max_length=50, db_index=True)

    activity_value = models.TextField(null=True, blank=True)

    # Title of the course / apprenticeship / job "card" the action refers to
    # (frontend-supplied, e.g. for provider-link clicks). null for events that
    # don't reference a specific titled card.
    card = models.CharField(max_length=255, null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "analytics_user_activity"
        indexes = [
            # Global "top N by type over time" reports
            models.Index(fields=["activity_type", "created_at"]),
            # Per-career drill-down ("how did this career perform?")
            models.Index(fields=["career", "activity_type"]),
            # Per-user drill-down ("what did this user do?")
            models.Index(fields=["user", "activity_type"]),
            # User x career queries (e.g. "did user X save career Y?")
            models.Index(fields=["user", "career", "activity_type"]),
        ]
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.activity_type} user={self.user_id} career={self.career_id}"


class ProviderLead(models.Model):
    """
    GDPR-isolated table for actual contactable leads.

    `consent_given` events ALSO get logged into UserActivity, but the
    identifiable contact data lives ONLY here. This keeps analytics
    anonymous-safe while still letting us export a clean leads list
    to providers after explicit consent.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_leads",
    )

    career = models.ForeignKey(
        "careers.Career",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_leads",
    )

    # Which route the lead is for. IDs overlap across the three tables (the same
    # id can be a Course AND a Job), so we store the type AND the id together —
    # the id alone is ambiguous and can't be resolved back to a provider record.
    ROUTE_COURSE = "course"
    ROUTE_APPRENTICESHIP = "apprenticeship"
    ROUTE_JOB = "job"
    ROUTE_CHOICES = [
        (ROUTE_COURSE, "Course"),
        (ROUTE_APPRENTICESHIP, "Apprenticeship"),
        (ROUTE_JOB, "Job"),
    ]
    route_type = models.CharField(
        max_length=20, choices=ROUTE_CHOICES, blank=True, default=""
    )
    route_item_id = models.PositiveIntegerField(null=True, blank=True)

    # Explicit consent flag sent by the frontend (true = agreed to be contacted).
    consented = models.BooleanField(default=False)

    # --- Lead contact details (fetched server-side from the user + profile) ---
    name = models.CharField(max_length=255, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    address = models.CharField(max_length=300, blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")

    # --- Route item details (fetched server-side from the resolved item) ---
    card_name = models.CharField(max_length=500, blank=True, default="")   # course/job/apprenticeship title
    subcategory = models.CharField(max_length=255, blank=True, default="")
    salary_or_cost = models.CharField(max_length=255, blank=True, default="")  # job/appr salary or course cost
    provider_name = models.CharField(max_length=255, blank=True, default="")
    provider_type = models.CharField(max_length=64, blank=True, default="")

    consent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "analytics_provider_lead"
        indexes = [
            models.Index(fields=["provider_name"]),
            models.Index(fields=["user", "consent_at"]),
            models.Index(fields=["route_type", "route_item_id"]),
        ]
        ordering = ("-consent_at",)

    def __str__(self):
        return f"Lead<user={self.user_id} provider={self.provider_name}>"
