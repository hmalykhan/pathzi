from rest_framework import permissions

class CareerPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        action = getattr(view, "action", None)

        allowed = {
            "save", "list", "my", "retrieve", "unsave",
            "courses", "jobs", "apprenticeships",
            "report",  # ✅ add
        }

        # ✅ Avoid confusing 403 when action can't be resolved (wrong method etc.)
        if action is None:
            return bool(request.user and request.user.is_authenticated)

        if action in allowed:
            return bool(request.user and request.user.is_authenticated)

        return bool(request.user and request.user.is_staff)