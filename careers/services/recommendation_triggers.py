from django.core.cache import cache

from careers.tasks import update_embedding_and_recs_task


def trigger_recs_debounced(user_id, timeout=60):
    key = f"pipeline_lock:{user_id}"

    if cache.add(key, True, timeout=timeout):
        update_embedding_and_recs_task.delay(user_id)
        return True

    return False