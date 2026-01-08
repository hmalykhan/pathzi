# billing/admin.py
from django.contrib import admin
from .models import BillingProfile, StripeEvent


@admin.register(BillingProfile)
class BillingProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subscription_status",
        "is_active",
        "current_period_end",
        "stripe_customer_id",
        "stripe_subscription_id",
        "updated_at",
    )
    list_filter = ("subscription_status", "updated_at", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "stripe_subscription_id",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)

    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Stripe", {"fields": ("stripe_customer_id", "stripe_subscription_id")}),
        ("Subscription", {"fields": ("subscription_status", "current_period_end")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_id", "event_type", "received_at")
    list_filter = ("event_type", "received_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("event_id", "event_type", "payload", "received_at")
    ordering = ("-received_at",)
