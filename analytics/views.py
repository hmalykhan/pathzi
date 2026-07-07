"""
Public analytics endpoints (frontend-fired).

- ActivityIngestAPI  POST /analytics/activity/  -> queue events (Lane B)
- ConsentAPI         POST /analytics/consent/   -> ProviderLead (synchronous)
"""

import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


@staff_member_required
def analytics_dashboard(request):
    """Staff-only HTML dashboard that visualises the /analytics/admin/ reports."""
    return render(request, "analytics/dashboard.html")

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


def _date(request, key):
    """Read a YYYY-MM-DD query param as a date, or None."""
    from datetime import datetime
    raw = request.query_params.get(key)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


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
                    "card": event.get("card"),
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
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(reports.overview(
            date_from=_date(request, "date_from"),
            date_to=_date(request, "date_to"),
        ))


class TopCareersReportAPI(APIView):
    """Top-N careers for an activity type, e.g. /top/career_viewed/."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, activity_type):
        data = reports.top_careers(
            activity_type,
            offset=_int(request, "offset", 0),
            limit=_int(request, "limit", 10),
            date_from=_date(request, "date_from"),
            date_to=_date(request, "date_to"),
        )
        return Response({"activity_type": activity_type, **data})


class CareerActivityUsersAPI(APIView):
    """Users who did one activity on one career (lazy hover popup)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, activity_type, career_id):
        return Response(
            reports.career_activity_users(
                career_id,
                activity_type,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CareerEngagementUsersAPI(APIView):
    """Top careers for an activity type, each with the users who did it."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, activity_type):
        return Response(
            reports.career_engagement_users(
                activity_type,
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CareerSwipeUsersAPI(APIView):
    """Users who swiped on one career, with their right/left counts."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, career_id):
        return Response(
            reports.career_swipe_users(
                career_id,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class SwipeDirectionUsersAPI(APIView):
    """Careers + users for one swipe direction (right=like / left=skip)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, direction):
        direction = "right" if direction == "right" else "left"
        return Response(
            reports.swipe_direction_users(
                direction,
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class SwipeEngagementUsersAPI(APIView):
    """Careers ranked by right-swipes, each with its swiping users (right/left)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.swipe_engagement_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class LikeVsSkipReportAPI(APIView):
    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.like_vs_skip_ratio(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class RouteClicksReportAPI(APIView):
    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.route_clicks(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
            )
        )


class RouteClicksByCareerAPI(APIView):
    """Careers with their course / apprenticeship / job route-click counts."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.route_clicks_by_career(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CareerRouteUsersAPI(APIView):
    """Users who clicked routes on one career (per-user course/apprenticeship/job)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, career_id):
        return Response(
            reports.career_route_users(
                career_id,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class RouteEngagementUsersAPI(APIView):
    """Careers ranked by route clicks, each with its clicking users."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.route_engagement_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class ProviderClicksReportAPI(APIView):
    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.provider_clicks(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
            )
        )


class ProviderCardsAPI(APIView):
    """Titled cards (course/apprenticeship/job) with career, route and clicks."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.provider_cards(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CardClickUsersAPI(APIView):
    """Users who clicked one titled card (lazy hover popup)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.card_click_users(
                request.query_params.get("card") or "",
                career_id=_int(request, "career_id", 0) or None,
                route=request.query_params.get("route") or None,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class ProviderCardUsersAPI(APIView):
    """Every titled card with its clicking users (grouped View all)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.provider_card_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class ConsentLeadsReportAPI(APIView):
    """Careers generating consent leads (from ProviderLead)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.consent_leads(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CareerLeadUsersAPI(APIView):
    """Users who generated consent leads for one career (lazy hover popup)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, career_id):
        return Response(
            reports.career_lead_users(
                career_id,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class LeadEngagementUsersAPI(APIView):
    """Careers ranked by leads, each with the users who generated them."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.lead_engagement_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class TimeseriesReportAPI(APIView):
    """User activity by date. Optional ?type=<activity_type>&date_from=&date_to=."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            {
                "results": reports.timeseries(
                    activity_type=request.query_params.get("type") or None,
                    date_from=_date(request, "date_from"),
                    date_to=_date(request, "date_to"),
                )
            }
        )


class CareersListAPI(APIView):
    """List careers with activity counts. Optional ?q=&date_from=&date_to=&limit=."""

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request):
        return Response(
            reports.careers_list(
                q=request.query_params.get("q") or None,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 50),
            )
        )


class CareerReportAPI(APIView):
    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, career_id):
        return Response(
            reports.career_summary(
                career_id,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class EventsListAPI(APIView):
    """
    Flat event feed for KPI-card drill-downs.
    ?types=career_swiped_right,career_swiped_left  &q=  &date_from=  &date_to=  &limit=
    """

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request):
        raw = request.query_params.get("types") or request.query_params.get("type")
        types = [t.strip() for t in raw.split(",") if t.strip()] if raw else None
        return Response(
            reports.events_list(
                activity_types=types,
                q=request.query_params.get("q") or None,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 50),
            )
        )


class UsersListAPI(APIView):
    """List all users with activity counts. Optional ?q=&date_from=&date_to=&limit=."""

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request):
        return Response(
            reports.users_list(
                q=request.query_params.get("q") or None,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 50),
            )
        )


class UserReportAPI(APIView):
    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request, user_id):
        return Response(
            reports.user_summary(
                user_id,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
                # allow the PDF export to pull the full timeline, not just 200
                timeline_limit=_int(request, "limit", 200),
            )
        )


class PopularByLocationReportAPI(APIView):
    """Popular careers grouped by user's profile city. Optional ?city=&days=."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.popular_careers_by_location(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class SearchedCareersReportAPI(APIView):
    """Careers searched by users, paired with the searched location. Ranked by count."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.searched_careers(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class SearchedCareerUsersAPI(APIView):
    """Users who searched one career in one location (lazy hover popup). ?career_id=&city="""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.searched_career_users(
                career_id=_int(request, "career_id", 0),
                city=request.query_params.get("city") or "",
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class SearchedCareerEngagementUsersAPI(APIView):
    """(career, city) pairs each with the users who searched them (grouped View all)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.searched_career_engagement_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class CityUsersAPI(APIView):
    """Users living in one city, with their career-view counts (lazy hover)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        city = request.query_params.get("city") or ""
        return Response(
            reports.city_users(
                city,
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )


class LocationEngagementUsersAPI(APIView):
    """Cities ranked by views, each with the users living there."""

    permission_classes = [IsStaffUser]
    throttle_classes = []  # staff-only reports; dashboard fires ~9 calls/load

    def get(self, request):
        return Response(
            reports.location_engagement_users(
                offset=_int(request, "offset", 0),
                limit=_int(request, "limit", 10),
                date_from=_date(request, "date_from"),
                date_to=_date(request, "date_to"),
            )
        )
