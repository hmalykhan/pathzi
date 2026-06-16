from django.urls import path

from .views import (
    ActivityIngestAPI,
    CareerReportAPI,
    CareersListAPI,
    ConsentAPI,
    ConsentLeadsReportAPI,
    EventsListAPI,
    LikeVsSkipReportAPI,
    OverviewReportAPI,
    PopularByLocationReportAPI,
    ProviderClicksReportAPI,
    RouteClicksReportAPI,
    TimeseriesReportAPI,
    TopCareersReportAPI,
    UserReportAPI,
    UsersListAPI,
    analytics_dashboard,
)

urlpatterns = [
    # ---- Public (frontend) ----
    path("activity/", ActivityIngestAPI.as_view(), name="analytics-activity"),
    path("consent/", ConsentAPI.as_view(), name="analytics-consent"),

    # ---- Admin dashboard (staff-only HTML page) ----
    path("dashboard/", analytics_dashboard, name="analytics-dashboard"),

    # ---- Admin reports (staff-only) ----
    path("admin/overview/", OverviewReportAPI.as_view(), name="analytics-overview"),
    path("admin/top/<str:activity_type>/", TopCareersReportAPI.as_view(), name="analytics-top"),
    path("admin/like-vs-skip/", LikeVsSkipReportAPI.as_view(), name="analytics-like-vs-skip"),
    path("admin/routes/", RouteClicksReportAPI.as_view(), name="analytics-routes"),
    path("admin/providers/", ProviderClicksReportAPI.as_view(), name="analytics-providers"),
    path("admin/consent-leads/", ConsentLeadsReportAPI.as_view(), name="analytics-consent-leads"),
    path("admin/timeseries/", TimeseriesReportAPI.as_view(), name="analytics-timeseries"),
    path("admin/by-location/", PopularByLocationReportAPI.as_view(), name="analytics-by-location"),
    path("admin/events/", EventsListAPI.as_view(), name="analytics-events"),
    path("admin/careers/", CareersListAPI.as_view(), name="analytics-careers"),
    path("admin/career/<int:career_id>/", CareerReportAPI.as_view(), name="analytics-career"),
    path("admin/users/", UsersListAPI.as_view(), name="analytics-users"),
    path("admin/user/<int:user_id>/", UserReportAPI.as_view(), name="analytics-user"),
]
