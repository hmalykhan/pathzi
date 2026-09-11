"""
Password-reset codes and single-use reset tokens.

Flow: forgot_password emails a 6-digit code -> verify_otp checks it and hands
back a single-use reset_token -> forgot_password_confirmation sets the new
password with that token (older app builds send the code instead).
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from accounts.models import OTP_TTL_SECONDS, PasswordResetOTP

OTP_LENGTH = 6
RESET_TOKEN_TTL_SECONDS = 10 * 60
MAX_OTP_ATTEMPTS = 5

# Stable error codes the app routes on (BACKEND.md section 3.11).
OTP_INVALID = "otp_invalid"
OTP_EXPIRED = "otp_expired"
OTP_THROTTLED = "otp_throttled"
TOKEN_INVALID = "token_invalid"
TOKEN_USED = "token_used"
TOKEN_EXPIRED = "token_expired"
PASSWORD_WEAK = "password_weak"
PASSWORD_MISMATCH = "password_mismatch"
MISSING_FIELDS = "missing_fields"

# Existing wording is kept where it existed: older app builds match on it.
MESSAGES = {
    OTP_INVALID: "Incorrect OTP",
    OTP_EXPIRED: "OTP expired",
    OTP_THROTTLED: "Too many attempts. Please request a new code.",
    TOKEN_INVALID: "Invalid reset token.",
    TOKEN_USED: "This reset token has already been used.",
    TOKEN_EXPIRED: "Reset token expired. Please verify your code again.",
    PASSWORD_MISMATCH: "Passwords does not match.",
    MISSING_FIELDS: "Missing fields",
}

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def issue_otp(user) -> str:
    """A new code for `user`. Resets the attempt count and voids any reset token."""
    otp = str(secrets.randbelow(900000) + 100000)
    PasswordResetOTP.objects.update_or_create(
        user=user,
        defaults={
            "otp": otp,
            "created_at": timezone.now(),
            "attempts": 0,
            "reset_token_hash": "",
            "reset_token_expires_at": None,
            "reset_token_used_at": None,
        },
    )
    return otp


def check_otp(record, otp: str):
    """None if `otp` is the live code on `record`, else an error code. Counts wrong guesses."""
    if record is None or not record.otp:
        return OTP_INVALID
    if record.attempts >= MAX_OTP_ATTEMPTS:
        return OTP_THROTTLED
    if not record.is_valid():
        return OTP_EXPIRED
    if not _same(record.otp, otp):
        PasswordResetOTP.objects.filter(pk=record.pk).update(attempts=F("attempts") + 1)
        record.attempts += 1
        return OTP_THROTTLED if record.attempts >= MAX_OTP_ATTEMPTS else OTP_INVALID
    return None


def issue_reset_token(record) -> str:
    """Swap a verified code for a single-use token. The code can't be used again."""
    token = "rt_" + secrets.token_urlsafe(32)
    record.otp = ""
    record.reset_token_hash = _hash(token)
    record.reset_token_expires_at = timezone.now() + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)
    record.reset_token_used_at = None
    record.save(update_fields=["otp", "reset_token_hash", "reset_token_expires_at", "reset_token_used_at"])
    return token


def check_reset_token(record, token: str):
    """None if `token` is live for `record`, else an error code."""
    if record is None or not record.reset_token_hash or not token:
        return TOKEN_INVALID
    if not _same(record.reset_token_hash, _hash(token)):
        return TOKEN_INVALID
    if record.reset_token_used_at:
        return TOKEN_USED
    if not record.reset_token_expires_at or record.reset_token_expires_at <= timezone.now():
        return TOKEN_EXPIRED
    return None


def mark_password_reset(record):
    """After a successful reset, neither the code nor the token works again."""
    record.otp = ""
    record.attempts = 0
    if record.reset_token_hash:
        record.reset_token_used_at = timezone.now()
    record.save(update_fields=["otp", "attempts", "reset_token_used_at"])
