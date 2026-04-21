# from celery import shared_task
# from django.contrib.auth.models import User
# from accounts.services.user_embeddings import generate_and_store_user_embedding


# @shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=2, retry_kwargs={'max_retries': 3})
# def update_user_embedding_task(self, user_id):
#     try:
#         user = User.objects.get(id=user_id)
#         generate_and_store_user_embedding(user)
#         print(f"✅ Embedding updated for user {user_id}")

#     except Exception as e:
#         print(f"❌ Error: {e}")
#         raise e  # 🔥 IMPORTANT → triggers retry