# # billing/admin.py
# from django.conf import settings
# from django.contrib import admin
# from django.utils.html import format_html

# from .models import BillingProfile, StripeEvent


# def _stripe_mode_prefix() -> str:
#     """
#     Stripe dashboard URLs use /test/ for test mode and no /test/ for live mode.
#     """
#     sk = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
#     return "test" if sk.startswith("sk_test_") else ""


# @admin.register(BillingProfile)
# class BillingProfileAdmin(admin.ModelAdmin):
#     list_display = (
#         "id",
#         "user",
#         "subscription_status",
#         "is_active",
#         "current_period_end",
#         "stripe_customer_link",
#         "stripe_subscription_link",
#         "updated_at",
#     )
#     list_filter = ("subscription_status", "updated_at", "created_at")
#     search_fields = (
#         "user__username",
#         "user__email",
#         "stripe_customer_id",
#         "stripe_subscription_id",
#     )
#     readonly_fields = (
#         "created_at",
#         "updated_at",
#         "stripe_customer_link",
#         "stripe_subscription_link",
#     )
#     ordering = ("-updated_at",)

#     fieldsets = (
#         ("User", {"fields": ("user",)}),
#         (
#             "Stripe",
#             {
#                 "fields": (
#                     "stripe_customer_id",
#                     "stripe_customer_link",
#                     "stripe_subscription_id",
#                     "stripe_subscription_link",
#                 )
#             },
#         ),
#         ("Subscription", {"fields": ("subscription_status", "current_period_end")}),
#         ("Timestamps", {"fields": ("created_at", "updated_at")}),
#     )

#     @admin.display(description="Stripe Customer")
#     def stripe_customer_link(self, obj: BillingProfile):
#         if not obj.stripe_customer_id:
#             return "-"
#         mode = _stripe_mode_prefix()
#         url = f"https://dashboard.stripe.com/{mode + '/' if mode else ''}customers/{obj.stripe_customer_id}"
#         return format_html('<a href="{}" target="_blank">{}</a>', url, obj.stripe_customer_id)

#     @admin.display(description="Stripe Subscription")
#     def stripe_subscription_link(self, obj: BillingProfile):
#         if not obj.stripe_subscription_id:
#             return "-"
#         mode = _stripe_mode_prefix()
#         url = f"https://dashboard.stripe.com/{mode + '/' if mode else ''}subscriptions/{obj.stripe_subscription_id}"
#         return format_html('<a href="{}" target="_blank">{}</a>', url, obj.stripe_subscription_id)


# @admin.register(StripeEvent)
# class StripeEventAdmin(admin.ModelAdmin):
#     list_display = ("id", "event_id", "event_type", "received_at", "payload_preview")
#     list_filter = ("event_type", "received_at")
#     search_fields = ("event_id", "event_type")
#     readonly_fields = ("event_id", "event_type", "payload", "received_at")
#     ordering = ("-received_at",)

#     @admin.display(description="Payload Preview")
#     def payload_preview(self, obj: StripeEvent):
#         text = str(obj.payload)
#         return (text[:120] + "...") if len(text) > 120 else text







from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from .models import BillingProfile, StripeEvent


def _stripe_mode_prefix() -> str:
    sk = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    return "test" if sk.startswith("sk_test_") else ""


@admin.register(BillingProfile)
class BillingProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "plan_id",
        "subscription_status",
        "is_active",
        "current_period_end",
        "pending_plan_id",
        "pending_change_at",
        "stripe_customer_link",
        "stripe_subscription_link",
        "updated_at",
    )
    list_filter = ("plan_id", "subscription_status", "updated_at", "created_at")
    search_fields = ("user__username", "user__email", "stripe_customer_id", "stripe_subscription_id", "stripe_price_id")
    readonly_fields = ("created_at", "updated_at", "stripe_customer_link", "stripe_subscription_link")
    ordering = ("-updated_at",)

    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Stripe", {"fields": ("stripe_customer_id", "stripe_customer_link", "stripe_subscription_id", "stripe_subscription_link")}),
        ("Plan", {"fields": ("plan_id", "stripe_price_id", "pending_plan_id", "pending_change_at", "stripe_schedule_id")}),
        ("Subscription", {"fields": ("subscription_status", "current_period_end")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Stripe Customer")
    def stripe_customer_link(self, obj: BillingProfile):
        if not obj.stripe_customer_id:
            return "-"
        mode = _stripe_mode_prefix()
        url = f"https://dashboard.stripe.com/{mode + '/' if mode else ''}customers/{obj.stripe_customer_id}"
        return format_html('<a href="{}" target="_blank">{}</a>', url, obj.stripe_customer_id)

    @admin.display(description="Stripe Subscription")
    def stripe_subscription_link(self, obj: BillingProfile):
        if not obj.stripe_subscription_id:
            return "-"
        mode = _stripe_mode_prefix()
        url = f"https://dashboard.stripe.com/{mode + '/' if mode else ''}subscriptions/{obj.stripe_subscription_id}"
        return format_html('<a href="{}" target="_blank">{}</a>', url, obj.stripe_subscription_id)


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_id", "event_type", "received_at", "payload_preview")
    list_filter = ("event_type", "received_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("event_id", "event_type", "payload", "received_at")
    ordering = ("-received_at",)

    @admin.display(description="Payload Preview")
    def payload_preview(self, obj: StripeEvent):
        text = str(obj.payload)
        return (text[:120] + "...") if len(text) > 120 else text


