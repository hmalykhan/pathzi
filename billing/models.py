
# billing/models.py
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

    PLAN_CHOICES = [
        ("free", "Free"),
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing",
    )

    stripe_customer_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    plan_id = models.CharField(max_length=20, choices=PLAN_CHOICES, default="free")
    stripe_price_id = models.CharField(max_length=64, blank=True, null=True)

    pending_plan_id = models.CharField(max_length=20, choices=PLAN_CHOICES, blank=True, null=True)
    pending_change_at = models.DateTimeField(blank=True, null=True)
    stripe_schedule_id = models.CharField(max_length=64, blank=True, null=True)

    subscription_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="none")
    current_period_end = models.DateTimeField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self) -> bool:
        """
        ✅ STRICT RULE:
        Active = ONLY paid plans (monthly/quarterly/yearly)
        AND Stripe status == active
        AND current_period_end exists and is in the future.
        """
        if self.plan_id not in ("monthly", "quarterly", "yearly"):
            return False

        # If you want trialing to count, change to:
        # if self.subscription_status not in ("active", "trialing"):
        #     return False
        if self.subscription_status != "active":
            return False

        if not self.current_period_end:
            return False

        return self.current_period_end > timezone.now()


class StripeEvent(models.Model):
    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=128)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)