"""
Public analytics endpoints (frontend-fired).

- ActivityIngestAPI  POST /analytics/activity/  -> queue events (Lane B)
- ConsentAPI         POST /analytics/consent/   -> ProviderLead (synchronous)
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import constants as C
from . import reports
from .models import ProviderLead
from .permissions import IsStaffUser
from .serializers import ActivityBatchSerializer, ConsentSerializer
from .services import log_activity, queue_events, sanitize_metadata
from .throttles import AnalyticsIngestThrottle

logger = logging.getLogger(__name__)


def _int(request, key, default):
    """Read an int query param, falling back to default on bad input."""
    try:
        return int(request.query_params.get(key, default))
    except (TypeError, ValueError):
        return default


class ActivityIngestAPI(APIView):
    """
    Accepts a batch of 1-200 frontend events and pushes them onto the Redis
    queue (Lane B). Returns immediately; the beat flusher writes them to the
    DB. The user is taken from the auth token — never trusted from the body.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [AnalyticsIngestThrottle]

    def post(self, request):
        serializer = ActivityBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = request.user.id
        events = []
        for event in serializer.validated_data["events"]:
            events.append(
                {
                    "user_id": user_id,  # forced from auth, ignore any client value
                    "career_id": event.get("career_id"),
                    "route_id": event.get("route_id"),
                    "activity_type": event["activity_type"],
                    "activity_value": event.get("activity_value"),
                    # GDPR: strip any emails/phones the frontend may have included
                    "metadata": sanitize_metadata(event.get("metadata") or {}),
                }
            )

        queued = queue_events(events)
        return Response({"status": True, "queued": queued}, status=status.HTTP_202_ACCEPTED)


class ConsentAPI(APIView):
    """
    Records explicit consent to be contacted by a provider. Writes a
    ProviderLead row SYNCHRONOUSLY (so the consent timestamp is provable),
    and also logs an anonymous consent_given event into UserActivity.
    Contact data lives only in ProviderLead — never in analytics metadata.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ConsentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lead = ProviderLead.objects.create(
            user=request.user,
            career_id=data.get("career_id"),
            provider_name=data["provider_name"],
            provider_type=data.get("provider_type", ""),
            contact_email=data["contact_email"],
        )

        # Anonymous analytics trail — NO email/contact data in metadata.
        log_activity(
            user=request.user,
            activity_type=C.CONSENT_GIVEN,
            career=data.get("career_id"),
            metadata={
                "provider_name": data["provider_name"],
                "provider_type": data.get("provider_type", ""),
            },
        )

        return Response(
            {
                "status": True,
                "message": "Consent recorded.",
                "lead_id": lead.id,
                "consent_at": lead.consent_at,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin reports (staff-only). All read-only GET endpoints powered by reports.py
# ---------------------------------------------------------------------------


class OverviewReportAPI(APIView):
    """Dashboard header totals: users, views, swipes, right/left, saves."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(reports.overview(days=_int(request, "days", 30)))


class TopCareersReportAPI(APIView):
    """Top-N careers for an activity type, e.g. /top/career_viewed/."""

    permission_classes = [IsStaffUser]

    def get(self, request, activity_type):
        return Response(
            {
                "activity_type": activity_type,
                "results": reports.top_careers(
                    activity_type,
                    limit=_int(request, "limit", 20),
                    days=_int(request, "days", 0) or None,
                ),
            }
        )


class LikeVsSkipReportAPI(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {
                "results": reports.like_vs_skip_ratio(
                    limit=_int(request, "limit", 20),
                    days=_int(request, "days", 0) or None,
                )
            }
        )


class RouteClicksReportAPI(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {"results": reports.route_clicks(limit=_int(request, "limit", 20))}
        )


class ProviderClicksReportAPI(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {"results": reports.provider_clicks(limit=_int(request, "limit", 20))}
        )


class ConsentLeadsReportAPI(APIView):
    """Careers generating consent leads (from ProviderLead)."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {"results": reports.consent_leads(limit=_int(request, "limit", 20))}
        )


class TimeseriesReportAPI(APIView):
    """User activity by date. Optional ?type=<activity_type>&days=<n>."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {
                "results": reports.timeseries(
                    activity_type=request.query_params.get("type") or None,
                    days=_int(request, "days", 30),
                )
            }
        )


class CareerReportAPI(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request, career_id):
        return Response(reports.career_summary(career_id))


class UserReportAPI(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request, user_id):
        return Response(reports.user_summary(user_id))


class PopularByLocationReportAPI(APIView):
    """Popular careers grouped by user's profile city. Optional ?city=&days=."""

    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {
                "results": reports.popular_careers_by_location(
                    limit_per_city=_int(request, "limit", 10),
                    days=_int(request, "days", 0) or None,
                    city=request.query_params.get("city") or None,
                )
            }
        )
