"""
Celery tasks for the analytics module.

Lane A: record_activity_task — one task per backend-fired event.
Lane B: flush_activity_queue — beat task (every 5s) that drains the
        analytics:queue Redis list into a single bulk_create.
"""

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from django_redis import get_redis_connection

from careers.models import Career

from .models import UserActivity
from .services import ANALYTICS_QUEUE_KEY

logger = logging.getLogger(__name__)

# Max events drained per flush run. At a 5s beat interval this supports
# ~100 events/sec sustained; bursts above that just take extra cycles.
FLUSH_BATCH_SIZE = 500


@shared_task(bind=True, max_retries=3)
def record_activity_task(self, payload):
    """Lane A worker — write one UserActivity row."""
    try:
        UserActivity.objects.create(
            user_id=payload.get("user_id"),
            career_id=payload.get("career_id"),
            route_id=payload.get("route_id"),
            activity_type=payload["activity_type"],
            activity_value=payload.get("activity_value"),
            card=payload.get("card"),
            metadata=payload.get("metadata") or {},
        )
        return "ok"
    except IntegrityError:
        # Stale FK (user/career deleted between event and write) — retrying
        # can never succeed, so drop the event instead of poisoning the queue.
        logger.warning("analytics: dropping event with stale FK: %r", payload)
        return "dropped"
    except Exception as exc:
        logger.exception("analytics: record_activity_task failed, retrying")
        raise self.retry(exc=exc, countdown=30)


def _coerce_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _route_str(value):
    """route_id is now a short string ("course"/"apprenticeship"/"job")."""
    if value is None or value == "":
        return None
    return str(value)[:20]


@shared_task
def flush_activity_queue():
    """
    Lane B worker — atomically take up to FLUSH_BATCH_SIZE events off the
    tail of the Redis list and insert them in one bulk_create.

    Bad items are logged and skipped; dangling user/career ids are nulled
    out (keeps the event, drops the broken reference) so one bad event can
    never abort the whole batch.
    """
    conn = get_redis_connection("default")

    # LRANGE + LTRIM in one MULTI/EXEC: grab the oldest N (list tail) and
    # remove exactly those, atomically even while new events LPUSH the head.
    pipe = conn.pipeline()
    pipe.lrange(ANALYTICS_QUEUE_KEY, -FLUSH_BATCH_SIZE, -1)
    pipe.ltrim(ANALYTICS_QUEUE_KEY, 0, -(FLUSH_BATCH_SIZE + 1))
    raw_items, _ = pipe.execute()

    if not raw_items:
        return 0

    # lrange returns newest-first within the slice; restore insertion order.
    raw_items.reverse()

    parsed = []
    for raw in raw_items:
        try:
            event = json.loads(raw)
            activity_type = event.get("activity_type")
            if not activity_type:
                raise ValueError("missing activity_type")
            parsed.append(event)
        except Exception:
            logger.warning("analytics: skipping bad queue item: %.300r", raw)

    if not parsed:
        return 0

    # Null out references to rows that no longer exist — bulk_create is one
    # INSERT, so a single dangling FK would otherwise fail the whole batch.
    user_ids = {e.get("user_id") for e in parsed if e.get("user_id")}
    career_ids = {_coerce_int(e.get("career_id")) for e in parsed} - {None}
    valid_users = set(
        get_user_model().objects.filter(id__in=user_ids).values_list("id", flat=True)
    )
    valid_careers = set(
        Career.objects.filter(id__in=career_ids).values_list("id", flat=True)
    )

    rows = []
    for event in parsed:
        user_id = event.get("user_id")
        career_id = _coerce_int(event.get("career_id"))
        metadata = event.get("metadata")
        rows.append(
            UserActivity(
                user_id=user_id if user_id in valid_users else None,
                career_id=career_id if career_id in valid_careers else None,
                route_id=_route_str(event.get("route_id")),
                activity_type=str(event["activity_type"])[:50],
                activity_value=event.get("activity_value"),
                card=(str(event["card"])[:255] if event.get("card") else None),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        )

    UserActivity.objects.bulk_create(rows, batch_size=FLUSH_BATCH_SIZE)
    logger.info("analytics: flushed %d events to DB", len(rows))
    return len(rows)


@shared_task
def purge_old_activity():
    """
    Retention purge (GDPR / storage hygiene). Deletes UserActivity rows older
    than settings.ANALYTICS_RETENTION_DAYS (default 365). ProviderLead is NOT
    purged here — consent records are kept until the user withdraws/deletes.
    """
    days = getattr(settings, "ANALYTICS_RETENTION_DAYS", 365)
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = UserActivity.objects.filter(created_at__lt=cutoff).delete()
    logger.info("analytics: purged %d events older than %d days", deleted, days)
    return deleted
