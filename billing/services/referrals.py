"""
Referrals: unique single-use codes, and the free days they earn.

The rules, from PART2_PAYMENTS.md section 2:

- Every share makes a NEW code. There is no permanent personal code, so a
  code that leaks is worth exactly one sign-up.
- A code is single-use: the first account to sign up with it consumes it.
- Codes expire after 30 days.
- A user cannot use their own code, and a new account can be credited to
  one referrer, once.
- Only NEW accounts earn credit. Signing in to an existing account does not.
- The invitee gets 7 bonus days (14 with the trial), the referrer gets 7.

Free days are ours - Apple and Google never see them. See access.py for how
they turn into access.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from billing.models import ReferralCode, ReferralCredit

logger = logging.getLogger(__name__)

CODE_EXPIRY_DAYS = 30
REFERRER_DAYS = 7
INVITEE_DAYS = 7

CODE_PREFIX = "PTH-"
# No 0/O/1/I/5/S - these codes get read off a screen and typed in by hand.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ2346789"
CODE_BODY_LENGTH = 6


class ReferralError(Exception):
    """A code could not be used. `code` is a stable string for the app."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def normalise(raw):
    """What the user typed -> what we store. Forgiving about case and spaces."""
    if not raw:
        return ""
    cleaned = "".join(str(raw).split()).upper().replace("–", "-").replace("—", "-")
    if cleaned and not cleaned.startswith(CODE_PREFIX):
        cleaned = CODE_PREFIX + cleaned.lstrip("-")
    return cleaned[:16]


def _new_code_string():
    return CODE_PREFIX + get_random_string(CODE_BODY_LENGTH, CODE_ALPHABET)


def create_code(user, channel="share", invited_email=None):
    """Make a fresh single-use code for this user."""
    expires_at = timezone.now() + timedelta(days=CODE_EXPIRY_DAYS)

    # get_random_string is cryptographically secure, so a clash is vanishingly
    # unlikely - but unique=True would raise, and losing a share to bad luck
    # is worse than a retry.
    for _ in range(5):
        candidate = _new_code_string()
        if not ReferralCode.objects.filter(code=candidate).exists():
            return ReferralCode.objects.create(
                code=candidate,
                created_by=user,
                channel=channel,
                invited_email=(invited_email or None),
                expires_at=expires_at,
            )
    raise ReferralError("code_generation_failed", "Could not create a code. Please try again.")


def grant_days(profile, days, subscribed=False):
    """
    Give a profile free days.

    Stacked on the end of whatever access it already has, so days are never
    swallowed by a trial that is still running. If the user is subscribed the
    days would be invisible, so they go to the bank instead and are applied
    when the subscription lapses (see access.py).

    Returns True if the days were banked.
    """
    if subscribed:
        profile.referral_days_banked = (profile.referral_days_banked or 0) + days
        profile.save(update_fields=["referral_days_banked"])
        return True

    now = timezone.now()
    # Start counting from the latest thing that is still in the future.
    starts = [d for d in (profile.trial_ends_at, profile.referral_access_until) if d and d > now]
    base = max(starts) if starts else now

    profile.referral_access_until = base + timedelta(days=days)
    profile.save(update_fields=["referral_access_until"])
    return False


def redeem(raw_code, new_user):
    """
    Apply a referral code to an account that has just been created.

    Raises ReferralError if the code cannot be used. Callers at sign-up must
    never let that failure stop the sign-up itself - a mistyped code is not a
    reason to refuse an account.
    """
    from accounts.models import UserProfile

    code_str = normalise(raw_code)
    if not code_str:
        raise ReferralError("referral_code_missing", "No referral code given.")

    with transaction.atomic():
        # Locked so two accounts racing on the same code cannot both win it.
        referral = (
            ReferralCode.objects.select_for_update()
            .filter(code=code_str)
            .first()
        )
        if referral is None:
            raise ReferralError("referral_code_invalid", "That referral code was not recognised.")

        if referral.used_at is not None:
            raise ReferralError("referral_code_used", "That referral code has already been used.")

        if referral.expires_at <= timezone.now():
            raise ReferralError("referral_code_expired", "That referral code has expired.")

        if referral.created_by_id == new_user.id:
            raise ReferralError("referral_code_own", "You cannot use your own referral code.")

        # One referrer per account, once.
        if ReferralCredit.objects.filter(user=new_user, kind="invitee").exists():
            raise ReferralError("referral_already_credited", "This account has already used a referral code.")

        referral.used_by = new_user
        referral.used_at = timezone.now()
        referral.save(update_fields=["used_by", "used_at"])

        invitee_profile = UserProfile.objects.filter(appuser=new_user).first()
        referrer_profile = UserProfile.objects.filter(appuser=referral.created_by_id).first()

        credits = []
        if invitee_profile is not None:
            banked = grant_days(invitee_profile, INVITEE_DAYS, subscribed=_is_subscribed(new_user))
            credits.append(ReferralCredit(
                user=new_user, code=referral, kind="invitee",
                days_awarded=INVITEE_DAYS, banked=banked,
            ))

        if referrer_profile is not None:
            banked = grant_days(referrer_profile, REFERRER_DAYS, subscribed=_is_subscribed(referral.created_by))
            credits.append(ReferralCredit(
                user=referral.created_by, code=referral, kind="referrer",
                days_awarded=REFERRER_DAYS, banked=banked,
            ))

        ReferralCredit.objects.bulk_create(credits)

    logger.info(
        "Referral redeemed: code=%s referrer=%s invitee=%s",
        code_str, referral.created_by_id, new_user.id,
    )
    return referral


def _is_subscribed(user):
    billing = getattr(user, "billing", None)
    return bool(billing and billing.is_active)


def try_redeem(raw_code, new_user):
    """
    Sign-up wrapper: apply the code if we can, and never raise.

    Returns what the app should show on the welcome screen.
    """
    if not raw_code:
        return {"applied": False, "code": None, "message": None, "days_awarded": 0}

    try:
        redeem(raw_code, new_user)
    except ReferralError as e:
        logger.info("Referral not applied for user=%s: %s", new_user.id, e.code)
        return {"applied": False, "code": e.code, "message": e.message, "days_awarded": 0}
    except Exception as e:                          # never break a sign-up
        logger.exception("Referral redemption error for user=%s: %s", new_user.id, e)
        return {"applied": False, "code": "referral_error", "message": "Referral could not be applied.", "days_awarded": 0}

    return {
        "applied": True,
        "code": None,
        "message": f"You got {INVITEE_DAYS} bonus days.",
        "days_awarded": INVITEE_DAYS,
    }


def summary_for(user):
    """Everything the referral screen shows."""
    codes = list(ReferralCode.objects.filter(created_by=user))
    credits = list(ReferralCredit.objects.filter(user=user))

    invites = [
        {
            "id": c.id,
            "code": c.code,
            "channel": c.channel,
            "email": c.invited_email,
            "status": c.status,
            "created_at": c.created_at,
            "expires_at": c.expires_at,
            "used_at": c.used_at,
        }
        for c in codes
    ]

    unseen = [
        {
            "id": c.id,
            "kind": c.kind,
            "days_awarded": c.days_awarded,
            "banked": c.banked,
            "created_at": c.created_at,
        }
        for c in credits if c.seen_at is None
    ]

    return {
        "friends_joined": sum(1 for c in codes if c.used_at is not None),
        "days_earned": sum(c.days_awarded for c in credits),
        "referrer_days": REFERRER_DAYS,
        "invitee_days": INVITEE_DAYS,
        "code_expiry_days": CODE_EXPIRY_DAYS,
        "invites": invites,
        "unseen_credits": unseen,
    }
