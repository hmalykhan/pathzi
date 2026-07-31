"""
Public analytics endpoints (frontend-fired).

- ActivityIngestAPI  POST /analytics/activity/  -> queue events (Lane B)
- ConsentAPI         POST /analytics/consent/   -> ProviderLead (synchronous)
"""

import logging

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


@user_passes_test(lambda u: u.is_active and u.is_staff, login_url="/login/")
def analytics_dashboard(request):
    """Staff-only HTML dashboard that visualises the /analytics/admin/ reports."""
    return render(request, "analytics/dashboard.html")

from . import constants as C
from . import reports
from . import warehouse
from accounts.models import UserProfile
from .models import ProviderLead
from .permissions import IsStaffUser
from .serializers import ActivityBatchSerializer, ConnectionSerializer, ConsentSerializer
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


def _lead_item_fields(route_type, item):
    """
    Derive the route-item details for a lead (card name, subcategory, salary/cost,
    provider name/type) from a resolved course/apprenticeship/job, so the frontend
    only needs to send route_type + route_item_id.
    """
    subcategory = getattr(item, "subcategory", "") or ""
    if route_type == "course":
        return {
            "card_name": getattr(item, "course_name", "") or "",
            "subcategory": subcategory,
            "salary_or_cost": getattr(item, "cost", "") or "",
            "provider_name": getattr(item, "college_name", "") or getattr(item, "awarding_organization", ""),
            "provider_type": "college",
        }
    if route_type == "apprenticeship":
        return {
            "card_name": getattr(item, "title", "") or "",
            "subcategory": subcategory,
            "salary_or_cost": getattr(item, "wage", "") or "",
            "provider_name": getattr(item, "employer_name", "") or getattr(item, "training_provider", ""),
            "provider_type": "employer",
        }
    if route_type == "job":
        return {
            "card_name": getattr(item, "title", "") or "",
            "subcategory": subcategory,
            "salary_or_cost": getattr(item, "salary", "") or "",
            "provider_name": getattr(item, "company", "") or "",
            "provider_type": "company",
        }
    return {"card_name": "", "subcategory": "", "salary_or_cost": "", "provider_name": "", "provider_type": ""}


class ConsentAPI(APIView):
    """
    Records explicit consent to be contacted by a provider. The frontend sends
    only route_type + route_item_id + consented; provider name/type are fetched
    from the resolved route item and contact email from the authenticated user.
    Writes a ProviderLead row SYNCHRONOUSLY (so the consent timestamp is provable)
    and logs an anonymous consent_given event into UserActivity.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ConsentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        route_type = data["route_type"]
        item = data["route_item"]  # already resolved by the serializer
        consented = data.get("consented", False)

        # Route-item details (card, subcategory, salary/cost, provider).
        f = _lead_item_fields(route_type, item)

        # Lead contact details from the authenticated user + their profile.
        user = request.user
        profile = UserProfile.objects.filter(appuser=user).first()

        lead = ProviderLead.objects.create(
            user=user,
            route_type=route_type,
            route_item_id=data["route_item_id"],
            consented=consented,
            name=(user.get_full_name() or user.get_username() or "").strip(),
            contact_email=user.email or "",
            address=getattr(profile, "address", "") or "",
            city=getattr(profile, "city", "") or "",
            card_name=f["card_name"],
            subcategory=f["subcategory"],
            salary_or_cost=f["salary_or_cost"],
            provider_name=f["provider_name"],
            provider_type=f["provider_type"],
        )

        # Anonymous analytics trail — NO name/email/contact data in metadata.
        log_activity(
            user=user,
            activity_type=C.CONSENT_GIVEN,
            route_id=route_type,
            metadata={
                "provider_name": f["provider_name"],
                "provider_type": f["provider_type"],
                "route_type": route_type,
                "route_item_id": data["route_item_id"],
                "card_name": f["card_name"],
                "subcategory": f["subcategory"],
                "consented": consented,
            },
        )

        return Response(
            {
                "status": True,
                "message": "Consent recorded.",
                "consent_id": lead.id,
                "route_type": lead.route_type,
                "provider_name": lead.provider_name,
                "consent_at": lead.consent_at,
            },
            status=status.HTTP_201_CREATED,
        )


class MyConnectionsAPI(APIView):
    """
    Returns ALL of the logged-in user's connections (ProviderLead rows) with the
    full stored data. Powers the user's "connected" list on the frontend.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Only genuinely connected rows (consented=True). consented defaults to
        # False; the frontend sets it True on connect, so unconsented/disconnected
        # rows are excluded from the user's connected list.
        leads = ProviderLead.objects.filter(user=request.user, consented=True)  # newest first (model ordering)
        data = ConnectionSerializer(leads, many=True).data
        return Response({"status": True, "count": len(data), "results": data})


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


class WarehouseListAPI(APIView):
    """Paginated browse of a scraped dataset (courses / apprenticeships / jobs)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request, dataset):
        if dataset not in warehouse.DATASETS:
            return Response({"detail": "Unknown dataset."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            warehouse.warehouse_list(
                dataset,
                q=request.query_params.get("q") or None,
                city=request.query_params.get("city") or None,
                offset=_int(request, "offset", 0),
                limit=min(_int(request, "limit", 50), 200),
            )
        )


class WarehouseDetailAPI(APIView):
    """Full record for one row in a scraped dataset."""

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request, dataset, obj_id):
        if dataset not in warehouse.DATASETS:
            return Response({"detail": "Unknown dataset."}, status=status.HTTP_404_NOT_FOUND)
        data = warehouse.warehouse_detail(dataset, obj_id)
        if not data:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(data)


class WarehouseCitiesAPI(APIView):
    """Distinct city list for a dataset (populates the city dropdown)."""

    permission_classes = [IsStaffUser]
    throttle_classes = []

    def get(self, request, dataset):
        if dataset not in warehouse.DATASETS:
            return Response({"detail": "Unknown dataset."}, status=status.HTTP_404_NOT_FOUND)
        return Response(warehouse.warehouse_cities(dataset))
