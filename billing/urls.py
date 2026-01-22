# from django.urls import path
# from .views import SubscribeView, SubscriptionStatusView, CustomerPortalView, CancelSubscriptionView
# from .webhooks import stripe_webhook
# from django.views.decorators.csrf import csrf_exempt

# urlpatterns = [
#     path("subscribe/", SubscribeView.as_view(), name="billing-subscribe"),
#     path("status/", SubscriptionStatusView.as_view(), name="billing-status"),
#     path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
#     path("webhook/", csrf_exempt(stripe_webhook), name="stripe-webhook"),
#     path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
# ]




from django.urls import path
from .views import (
    SubscribeView,
    SubscriptionStatusView,
    ChangePlanView,
    CustomerPortalView,
    CancelSubscriptionView,
    ResumeSubscriptionView,
)
from .webhooks import stripe_webhook

urlpatterns = [
    path("subscribe/", SubscribeView.as_view(), name="billing-subscribe"),
    path("status/", SubscriptionStatusView.as_view(), name="billing-status"),
    path("change-plan/", ChangePlanView.as_view(), name="billing-change-plan"),
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("resume/", ResumeSubscriptionView.as_view(), name="billing-resume"),
    path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
    path("webhook/", stripe_webhook, name="stripe-webhook"),
]

