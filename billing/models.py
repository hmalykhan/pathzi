from django.conf import settings
from django.db import models
from django.utils import timezone


class BillingProfile(models.Model):
    STATUS_CHOICES = [
        ("none", "None"),
        ("incomplete", "Incomplete"),
        ("trialing", "Trialing"),
        ("active", "Active"),
        ("past_due", "Past due"),
        ("canceled", "Canceled"),
        ("unpaid", "Unpaid"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="billing")
    stripe_customer_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    subscription_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="none")
    current_period_end = models.DateTimeField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self) -> bool:
        if self.subscription_status not in ("active", "trialing"):
            return False
        if self.current_period_end and self.current_period_end < timezone.now():
            return False
        return True


class StripeEvent(models.Model):
    """
    Used to de-duplicate webhook deliveries (Stripe can retry events).
    """
    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=128)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
