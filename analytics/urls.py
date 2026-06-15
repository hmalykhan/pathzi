from django.urls import path

from .views import (
    ActivityIngestAPI,
    CareerReportAPI,
    ConsentAPI,
    ConsentLeadsReportAPI,
    LikeVsSkipReportAPI,
    OverviewReportAPI,
    PopularByLocationReportAPI,
    ProviderClicksReportAPI,
    RouteClicksReportAPI,
    TimeseriesReportAPI,
    TopCareersReportAPI,
    UserReportAPI,
)

urlpatterns = [
    # ---- Public (frontend) ----
    path("activity/", ActivityIngestAPI.as_view(), name="analytics-activity"),
    path("consent/", ConsentAPI.as_view(), name="analytics-consent"),

    # ---- Admin reports (staff-only) ----
    path("admin/overview/", OverviewReportAPI.as_view(), name="analytics-overview"),
    path("admin/top/<str:activity_type>/", TopCareersReportAPI.as_view(), name="analytics-top"),
    path("admin/like-vs-skip/", LikeVsSkipReportAPI.as_view(), name="analytics-like-vs-skip"),
    path("admin/routes/", RouteClicksReportAPI.as_view(), name="analytics-routes"),
    path("admin/providers/", ProviderClicksReportAPI.as_view(), name="analytics-providers"),
    path("admin/consent-leads/", ConsentLeadsReportAPI.as_view(), name="analytics-consent-leads"),
    path("admin/timeseries/", TimeseriesReportAPI.as_view(), name="analytics-timeseries"),
    path("admin/by-location/", PopularByLocationReportAPI.as_view(), name="analytics-by-location"),
    path("admin/career/<int:career_id>/", CareerReportAPI.as_view(), name="analytics-career"),
    path("admin/user/<int:user_id>/", UserReportAPI.as_view(), name="analytics-user"),
]
