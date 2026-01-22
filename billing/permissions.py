# from rest_framework.permissions import BasePermission

# class HasActiveSubscription(BasePermission):
#     message = "Active subscription required."

#     def has_permission(self, request, view):
#         if request.method == "OPTIONS":
#             return True

#         user = request.user
#         if not user or not user.is_authenticated:
#             return False
        
#         # For real production you might want staff to always bypass subscription.
#         # For now, comment this out so you can test the 5-career limit:
#         # if user.is_staff:
#             # return True

#         billing = getattr(user, "billing", None)
#         return bool(billing and billing.is_active)





from datetime import datetime, timezone as dt_timezone


def ts_to_dt(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=dt_timezone.utc)


def subscription_period_end_dt(sub) -> "datetime | None":
    """
    Stripe may omit subscription.current_period_end on newer API versions.
    Fallback to subscription.items.data[].current_period_end.

    If multiple items exist, use the earliest end for safety.
    """
    ts = sub.get("current_period_end")
    if ts:
        return ts_to_dt(ts)

    items = (sub.get("items") or {}).get("data") or []
    ends = [it.get("current_period_end") for it in items if it.get("current_period_end")]
    if ends:
        return ts_to_dt(min(ends))

    return None

