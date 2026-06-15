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

    route_id = models.IntegerField(null=True, blank=True)

    activity_type = models.CharField(max_length=50, db_index=True)

    activity_value = models.TextField(null=True, blank=True)

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

    provider_name = models.CharField(max_length=255, blank=True, default="")
    provider_type = models.CharField(max_length=64, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    consent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "analytics_provider_lead"
        indexes = [
            models.Index(fields=["provider_name"]),
            models.Index(fields=["user", "consent_at"]),
        ]
        ordering = ("-consent_at",)

    def __str__(self):
        return f"Lead<user={self.user_id} provider={self.provider_name}>"
