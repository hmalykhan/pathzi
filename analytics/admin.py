from django.contrib import admin

from .models import ProviderLead, UserActivity


class ReadOnlyAdminMixin:
    """Activity logs are immutable — block writes from the admin UI."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = None


@admin.register(UserActivity)
class UserActivityAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "activity_type",
        "user",
        "career",
        "route_id",
        "activity_value_preview",
    )
    list_filter = ("activity_type", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "activity_type",
        "activity_value",
    )
    readonly_fields = (
        "user",
        "career",
        "route_id",
        "activity_type",
        "activity_value",
        "metadata",
        "created_at",
    )
    ordering = ("-created_at",)
    list_per_page = 100
    date_hierarchy = "created_at"

    @admin.display(description="value")
    def activity_value_preview(self, obj: UserActivity):
        if not obj.activity_value:
            return "-"
        text = str(obj.activity_value)
        return (text[:80] + "…") if len(text) > 80 else text


@admin.register(ProviderLead)
class ProviderLeadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "consent_at",
        "user",
        "provider_name",
        "provider_type",
        "contact_email",
        "career",
    )
    list_filter = ("provider_name", "provider_type", "consent_at")
    search_fields = (
        "user__username",
        "user__email",
        "contact_email",
        "provider_name",
    )
    readonly_fields = ("consent_at",)
    ordering = ("-consent_at",)
    date_hierarchy = "consent_at"
