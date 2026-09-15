"""
Cache calls that cannot take the site down.

Redis is both the cache and the Celery broker here, so when Upstash is
unreachable every `cache.get` and every `.delay()` raises. Unguarded, that
turns a cache outage into a 500 on ordinary pages - GET /careers/ among
them, which is the app's home screen.

Caching is an optimisation. Losing it should make the site slower, never
broken. These helpers keep the exact behaviour of django.core.cache when
Redis is healthy, and degrade to "no cache" when it is not.

Failures are logged once per key per process-minute so an outage does not
fill the log with the same line thousands of times.
"""
import logging
import time

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Anything the cache backend can raise when Redis is unreachable. Kept broad
# on purpose: redis, kombu and django_redis each raise their own types, and a
# missed one would defeat the whole point of this module.
CACHE_ERRORS = Exception

_last_logged = {}
_LOG_EVERY_SECONDS = 60


def _warn(operation, key, exc):
    now = time.time()
    last = _last_logged.get(operation, 0)
    if now - last > _LOG_EVERY_SECONDS:
        _last_logged[operation] = now
        logger.warning(
            "Cache unavailable (%s on %s): %s: %s. Continuing without cache.",
            operation, key, type(exc).__name__, exc,
        )


def cache_get(key, default=None):
    """Read from the cache. A cache outage looks like a miss."""
    try:
        return cache.get(key, default)
    except CACHE_ERRORS as e:
        _warn("get", key, e)
        return default


def cache_set(key, value, timeout=None):
    """Write to the cache. A cache outage means the value is simply not stored."""
    try:
        cache.set(key, value, timeout)
        return True
    except CACHE_ERRORS as e:
        _warn("set", key, e)
        return False


def cache_add(key, value=True, timeout=None):
    """
    Claim a lock.

    Returns False when the cache is unavailable - deliberately. These locks
    guard work that gets queued to Celery, and Celery's broker IS Redis, so
    if the cache is down the queued work could not run anyway. Saying "did
    not get the lock" skips work that was going to fail.
    """
    try:
        return bool(cache.add(key, value, timeout))
    except CACHE_ERRORS as e:
        _warn("add", key, e)
        return False


def cache_delete(key):
    """
    Drop a cache entry.

    A failure here is the least harmful of all: the entry keeps its old value
    until its timeout. Callers use this to invalidate, so the worst case is
    briefly stale data, not an error page.
    """
    try:
        cache.delete(key)
        return True
    except CACHE_ERRORS as e:
        _warn("delete", key, e)
        return False


def cache_delete_many(keys):
    ok = True
    for key in keys:
        ok = cache_delete(key) and ok
    return ok


def queue_task(task_callable, *args, **kwargs):
    """
    Send a job to Celery without letting a broker outage reach the user.

    Returns True if it was queued. Background work that does not happen is a
    delay; an exception here would be a broken page.
    """
    try:
        task_callable(*args, **kwargs)
        return True
    except CACHE_ERRORS as e:
        _warn("queue", getattr(task_callable, "__name__", "task"), e)
        return False
