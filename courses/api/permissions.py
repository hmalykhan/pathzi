from rest_framework import permissions


class CoursePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        action = getattr(view, "action", None)

        if action in {"save", "list", "my", "retrieve", "unsave", "bulk_interactions"}:
            return bool(request.user and request.user.is_authenticated)

        return bool(request.user and request.user.is_staff)
