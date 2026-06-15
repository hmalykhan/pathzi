from rest_framework.throttling import UserRateThrottle


class AnalyticsIngestThrottle(UserRateThrottle):
    """Rate limit for the public analytics ingest endpoint (rate in settings)."""

    scope = "analytics"
