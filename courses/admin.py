from django.contrib import admin
from .models import NcsCourse, CourseScrapeLog, Course


# If Course got registered somewhere else, this removes it.
try:
    admin.site.unregister(Course)
except admin.sites.NotRegistered:
    pass


@admin.register(CourseScrapeLog)
class CourseScrapeLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "run_id",
        "status",
        "course_id",
        "category",
        "keyword",
        "postcode",
        "distance",
    )
    list_filter = ("status", "category")
    search_fields = ("run_id", "course_id", "category", "keyword", "postcode", "start_url")
    ordering = ("-created_at",)


@admin.register(NcsCourse)
class NcsCourseAdmin(admin.ModelAdmin):
    list_display = (
        "course_name",
        "course_id",
        "category",
        "subcategory",
        "course_type",
        "learning_method",
        "duration",
        "cost",
        "scraped_at",
        "last_scrape_status",
        "last_checked_at",
    )
    list_filter = (
        "category",
        "subcategory",
        "course_type",
        "learning_method",
        "course_qualification_level",
        "scraped_at",
        "last_scrape_status",
    )
    search_fields = (
        "course_name",
        "course_id",
        "category",
        "subcategory",
        "course_url",
        "image_url",
        "course_type",
        "learning_method",
        "course_qualification_level",
        "attendance_pattern",
        "awarding_organization",
        "college_name",
        "address",
        "email",
        "phone",
        "website",
        "cost_description",
    )
    readonly_fields = (
        "scraped_at",
        "last_checked_at",
        "last_scrape_status",
        "last_scrape_message",
        "last_scrape_run_id",
    )
    ordering = ("-scraped_at", "course_name")
    list_per_page = 50

    fieldsets = (
        ("Course", {
            "fields": (
                "course_id",
                "course_url",
                "course_name",
                "category",
                "subcategory",
                "course_type",
                "course_qualification_level",
                "learning_method",
                "attendance_pattern",
                "course_hours",
                "course_stryd_time",
                "duration",
                "cost",
                "cost_description",
                "course_description",
            )
        }),
        ("Requirements", {"fields": ("who_this_course_is_for", "entry_reeq")}),
        ("Provider / Venue", {
            "fields": (
                "college_name",
                "awarding_organization",
                "address",
                "email",
                "phone",
                "website",
            )
        }),
        ("Meta", {
            "fields": (
                "scraped_at",
                "last_checked_at",
                "last_scrape_status",
                "last_scrape_message",
                "last_scrape_run_id",
            )
        }),
    )
