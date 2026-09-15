"""
Queue a recommendation rebuild, at most once per user per minute.

Both halves of this used to be able to take down a page: the debounce lock
lives in Redis, and Celery's broker is the same Redis. When Upstash was
unreachable, asking for the home screen raised instead of rendering.

Rebuilding recommendations is background work. If it cannot be queued the
user sees their existing recommendations a little longer, which is a far
better outcome than an error page.
"""
from pathzi.cache_utils import cache_add, queue_task

from careers.tasks import update_embedding_and_recs_task


def trigger_recs_debounced(user_id, timeout=60):
    """
    Returns True only if a rebuild was actually queued.

    cache_add returns False when Redis is down, so we skip quietly - the
    task could not have been delivered anyway, since the broker is Redis.
    """
    key = f"pipeline_lock:{user_id}"

    if cache_add(key, True, timeout=timeout):
        return queue_task(update_embedding_and_recs_task.delay, user_id)

    return False
