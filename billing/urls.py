from django.urls import path
from .views import SubscribeView, SubscriptionStatusView, CustomerPortalView
from .webhooks import stripe_webhook

urlpatterns = [
    path("subscribe/", SubscribeView.as_view(), name="billing-subscribe"),
    path("status/", SubscriptionStatusView.as_view(), name="billing-status"),
    path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
    path("webhook/", stripe_webhook, name="stripe-webhook"),
]