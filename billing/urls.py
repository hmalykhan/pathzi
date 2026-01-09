from django.urls import path
from .views import SubscribeView, SubscriptionStatusView, CustomerPortalView, CancelSubscriptionView
from .webhooks import stripe_webhook
from django.views.decorators.csrf import csrf_exempt

urlpatterns = [
    path("subscribe/", SubscribeView.as_view(), name="billing-subscribe"),
    path("status/", SubscriptionStatusView.as_view(), name="billing-status"),
    path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
    path("webhook/", csrf_exempt(stripe_webhook), name="stripe-webhook"),
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
]