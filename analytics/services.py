"""
Entry points for recording analytics events.

Lane A (backend-fired, low/medium volume):
    Call log_activity(...) from any view/service. It fires a Celery task
    and returns immediately. It NEVER raises — analytics must never break
    the user's actual request.

Lane B (frontend-fired, high volume):
    The public endpoint pushes raw event dicts onto a Redis list via
    queue_events(...). The flush_activity_queue beat task (every 5s)
    drains the list into one bulk_create.
"""

import json
import logging
import re

from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

# Redis list holding pending Lane B events (LPUSH on write, drained from
# the tail by flush_activity_queue so insertion order is preserved).
ANALYTICS_QUEUE_KEY = "analytics:queue"

# GDPR: analytics rows must stay anonymous-safe. We redact anything that
# looks like an email or phone number from frontend-supplied metadata.
# Contact data only belongs in ProviderLead (the consent flow), never here.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A run of 7+ digits possibly broken up by spaces/dashes/parens/dots/+.
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{5,}\d")
_REDACTED = "[redacted]"


def _redact_str(value):
    redacted = _EMAIL_RE.sub(_REDACTED, value)

    def _phone_sub(match):
        # Only redact if the match really contains 7+ digits — avoids nuking
        # short ids, prices, years, etc. that happen to have separators.
        digits = sum(ch.isdigit() for ch in match.group())
        return _REDACTED if digits >= 7 else match.group()

    return _PHONE_RE.sub(_phone_sub, redacted)


def sanitize_metadata(value):
    """
    Recursively strip emails/phone numbers from a metadata structure.
    Returns a cleaned copy; never raises (returns {} on unexpected input).
    """
    try:
        if isinstance(value, str):
            return _redact_str(value)
        if isinstance(value, dict):
            return {k: sanitize_metadata(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [sanitize_metadata(v) for v in value]
        return value
    except Exception:
        logger.warning("analytics: metadata sanitise failed", exc_info=True)
        return {}


def _pk_of(obj_or_id):
    """Accept a model instance or a raw id; return the id (or None)."""
    if obj_or_id is None:
        return None
    return getattr(obj_or_id, "pk", obj_or_id)


def log_activity(
    user=None,
    activity_type=None,
    career=None,
    route_id=None,
    activity_value=None,
    metadata=None,
):
    """
    Lane A entry point — record one backend-fired event asynchronously.

    `user` and `career` accept either model instances or raw ids.
    Returns True if the task was queued, False otherwise. Never raises.
    """
    if not activity_type:
        logger.warning("analytics: log_activity called without activity_type")
        return False

    try:
        user_id = _pk_of(user)
        # AnonymousUser has pk=None, which correctly logs as anonymous.

        payload = {
            "user_id": user_id,
            "career_id": _pk_of(career),
            "route_id": route_id,
            "activity_type": activity_type,
            "activity_value": activity_value,
            "metadata": metadata or {},
        }

        # Local import: tasks.py imports ANALYTICS_QUEUE_KEY from this
        # module, so importing tasks at module level would be circular.
        from .tasks import record_activity_task

        record_activity_task.delay(payload)
        return True
    except Exception:
        logger.warning(
            "analytics: failed to queue activity %s for user %r",
            activity_type,
            _pk_of(user),
            exc_info=True,
        )
        return False


def queue_events(events):
    """
    Lane B entry point — push pre-validated event dicts onto the Redis
    queue in one LPUSH. Returns the number queued (0 on failure).
    Never raises.
    """
    if not events:
        return 0

    try:
        payloads = [json.dumps(event, default=str) for event in events]
        conn = get_redis_connection("default")
        conn.lpush(ANALYTICS_QUEUE_KEY, *payloads)
        return len(payloads)
    except Exception:
        logger.warning("analytics: failed to queue %d events", len(events), exc_info=True)
        return 0
