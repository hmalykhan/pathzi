from rest_framework import permissions

class CoursePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True
        if view.action in {'save', 'list', 'my', 'retrieve', 'unsave'}:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_staff)        