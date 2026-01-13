from rest_framework import permissions

class CareerPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        action = getattr(view, "action", None)

        allowed = {
            "save", "list", "my", "retrieve", "unsave",
            "courses", "jobs", "apprenticeships",   # ✅ add these
        }

        if action in allowed:
            return bool(request.user and request.user.is_authenticated)

        return bool(request.user and request.user.is_staff)