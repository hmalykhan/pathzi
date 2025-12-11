from rest_framework import permissions

class JobPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if view.action in {'create', 'list', 'my'}:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_staff)        