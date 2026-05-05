from celery import shared_task
import traceback

from careers.services.recommendation_pipeline import update_embedding_and_recs_for_user


@shared_task
def debug_celery_task():
    print("Celery debug task is working.")
    return "ok"


@shared_task(bind=True, max_retries=3)
def update_embedding_and_recs_task(self, user_id):
    try:
        return update_embedding_and_recs_for_user(user_id)

    except Exception as exc:
        print("CELERY TASK FAILED")
        print("Exception type:", type(exc))
        print("Exception:", repr(exc))
        print(traceback.format_exc())

        raise self.retry(exc=exc, countdown=60)