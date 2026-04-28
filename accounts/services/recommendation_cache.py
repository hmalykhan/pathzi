def get_list_cache_key(user_id):
    return f"user_recs:{user_id}"

def get_saved_cache_key(user_id):
    return f"user_saved:{user_id}"

def get_explored_cache_key(user_id):
    return f"user_explored:{user_id}"

def get_embedding_schedule_lock_key(user_id):
    return f"embedding_schedule:{user_id}"

def get_recs_lock_key(user_id):
    return f"recs_lock:{user_id}"