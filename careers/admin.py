# careers/admin.py

from django.contrib import admin
from django.utils.html import format_html
from accounts.models import UserProfile

from .models import CareerJob, CareerScrapeLog, Career


# --- Make admin read-only (no add/change/delete) ---
class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = None  # optional: disables bulk delete action


# --- Scrape log admin (same as project 1 style) ---
@admin.register(CareerScrapeLog)
class CareerScrapeLogAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "run_id", "status", "route", "sub_type", "job_slug")
    list_filter = ("status", "route")
    search_fields = ("run_id", "sub_type", "job_slug", "job_url", "message")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


# --- Career job admin (read-only + image previews prefer dg_image_url) ---
@admin.register(CareerJob)
class CareerJobAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "career_type",
        "sub_type",
        "jobname",
        "salary",
        "hours",
        "image_open_link",
        "image_preview_thumb",
        "scraped_at",
        "last_scrape_status",
        "last_checked_at",
    )
    search_fields = ("jobname", "sub_type", "job_slug", "job_url", "image_url", "dg_image_url")
    list_filter = ("career_type", "sub_type", "last_scrape_status")
    ordering = ("-scraped_at",)

    readonly_fields = (
        "scraped_at",
        "last_checked_at",
        "last_scrape_status",
        "last_scrape_message",
        "last_scrape_run_id",
        "image_preview_large",
    )

    fieldsets = (
        ("Identity", {"fields": ("career_type", "sub_type", "job_slug", "job_url")}),
        # show both urls, but previews/open prefer dg_image_url
        ("Image", {"fields": ("image_url", "dg_image_url", "image_preview_large")}),
        ("Profile", {"fields": ("jobname", "job_description", "salary", "hours", "timings")}),
        (
            "How to become",
            {
                "fields": (
                    "how_to_become",
                    "college",
                    "college_entry_req",
                    "apprenticeship",
                    "apprenticeship_entry_req",
                )
            },
        ),
        (
            "Meta",
            {
                "fields": (
                    "scraped_at",
                    "last_checked_at",
                    "last_scrape_status",
                    "last_scrape_message",
                    "last_scrape_run_id",
                )
            },
        ),
    )

    # ---- helpers (display only; keeps image_url unchanged) ----
    def _preferred_image_url(self, obj: CareerJob) -> str:
        dg = (getattr(obj, "dg_image_url", "") or "").strip()
        if dg:
            return dg
        return (getattr(obj, "image_url", "") or "").strip()

    def image_open_link(self, obj: CareerJob):
        url = self._preferred_image_url(obj)
        if not url:
            return "-"
        label = "open (DO)" if (getattr(obj, "dg_image_url", "") or "").strip() else "open (Cloudinary)"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, label)

    image_open_link.short_description = "image"

    def image_preview_thumb(self, obj: CareerJob):
        url = self._preferred_image_url(obj)
        if not url:
            return "-"
        return format_html(
            '<img src="{}" style="height:40px;width:40px;object-fit:cover;border-radius:6px;border:1px solid #ddd;" />',
            url,
        )

    image_preview_thumb.short_description = "preview"

    def image_preview_large(self, obj: CareerJob):
        url = self._preferred_image_url(obj)
        if not url:
            return "No image_url / dg_image_url"
        return format_html(
            '<div style="margin-top:8px">'
            '<img src="{}" style="max-height:320px;max-width:320px;object-fit:cover;border-radius:10px;border:1px solid #ddd;" />'
            "</div>",
            url,
        )

    image_preview_large.short_description = "Preview"


# --- Hide proxy so you don't see both Career and CareerJob ---
try:
    admin.site.unregister(Career)
except admin.sites.NotRegistered:
    pass
