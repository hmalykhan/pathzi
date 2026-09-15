
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

    # --- Apple / Google in-app purchase, via RevenueCat -------------------
    # The app logs into RevenueCat as UserProfile.account_uuid, so this is
    # how a purchase finds its way back to exactly one Pathzi account.
    revenuecat_customer_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)

    store = models.CharField(max_length=20, blank=True, null=True)          # apple | google | test
    store_product_id = models.CharField(max_length=128, blank=True, null=True)

    # None means "we have never been told" - different from False.
    auto_renewing = models.BooleanField(blank=True, null=True)

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


class ReferralCode(models.Model):
    """
    One code per share. There is no permanent personal code: every time a user
    shares, a new code is made, and the first account to sign up with it uses
    it up. That is what stops a code being posted publicly and farmed.
    """

    CHANNEL_CHOICES = [
        ("share", "Shared by the user"),   # user copies it into WhatsApp etc.
        ("email", "Emailed by us"),
    ]

    code = models.CharField(max_length=16, unique=True, db_index=True)

    # SET_NULL, not CASCADE: if the person who shared this code later deletes
    # their account, the code row must survive. Deleting it would cascade to
    # ReferralCredit and silently erase the free days from the LEDGER of the
    # person who accepted the invitation - someone else's history.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="referral_codes",
        blank=True,
        null=True,
    )
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default="share")

    # Recorded so the referral screen can show who was invited. Deliberately
    # NOT checked when the code is used - the invitee may sign up with a
    # different address, and the PM asked for no strict email match.
    invited_email = models.EmailField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="referral_code_used",
        blank=True,
        null=True,
    )
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_by", "-created_at"])]

    def __str__(self):
        return self.code

    @property
    def is_expired(self):
        return self.used_at is None and self.expires_at <= timezone.now()

    @property
    def status(self):
        """What the referral screen shows: joined | expired | pending."""
        if self.used_at:
            return "joined"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"


class ReferralCredit(models.Model):
    """
    The ledger: one row per award of free days, so `days_earned` and the
    "you earned 7 days" popup are read from what actually happened rather
    than recalculated.
    """

    KIND_CHOICES = [
        ("referrer", "Days for the person who shared"),
        ("invitee", "Bonus days for the person who joined"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_credits",
    )
    code = models.ForeignKey(
        ReferralCode,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    days_awarded = models.PositiveSmallIntegerField()

    # True when the days went to the bank instead of straight to free access,
    # because the user was subscribed at the time and would have lost them.
    banked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    seen_at = models.DateTimeField(blank=True, null=True)   # popup shown once

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.user_id} +{self.days_awarded}d ({self.kind})"


class RevenueCatEvent(models.Model):
    """
    Every webhook we have already handled.

    RevenueCat retries a delivery until we answer 200, and a retry of a
    RENEWAL must not be applied twice. The unique event id is what makes
    handling a delivery idempotent.
    """

    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=64)
    app_user_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    # Kept so a delivery we could not match to an account can be found later
    # rather than disappearing into the log.
    handled = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return "%s %s" % (self.event_type, self.event_id)
