"""
Throttling that survives a Redis outage.

DRF's throttles call django.core.cache directly, so they never went through
pathzi/cache_utils.py. With Upstash unreachable, allow_request() raised
before the view ran and EVERY throttled endpoint returned 500 - including
login and sign-up. The rate limiter took the site down, which is a worse
outcome than the abuse it exists to prevent.

These fail open: if the cache cannot be read, the request is allowed and a
warning is logged. Rate limiting is a safeguard, not a correctness
requirement, and an attacker cannot reach the cache to disable it anyway.
"""
import logging
import time

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)

_last_warned = [0.0]
_WARN_EVERY = 60


def _warn(exc):
    now = time.time()
    if now - _last_warned[0] > _WARN_EVERY:
        _last_warned[0] = now
        logger.warning(
            "Throttle cache unavailable (%s: %s) - allowing requests through.",
            type(exc).__name__, exc,
        )


class ResilientThrottleMixin:
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception as e:          # cache down, not a throttling decision
            _warn(e)
            return True

    def throttle_success(self):
        try:
            return super().throttle_success()
        except Exception as e:
            _warn(e)
            return True


class ResilientUserRateThrottle(ResilientThrottleMixin, UserRateThrottle):
    """The project-wide default."""


class ResilientSimpleRateThrottle(ResilientThrottleMixin, SimpleRateThrottle):
    """Base for the OTP throttles."""
