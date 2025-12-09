from rest_framework import permissions
class AdminOnlyForCrud(permissions.BasePermission):
    # admin_only_actions = {'list', 'retrieve', 'create', 'update', 'partial_update', 'destroy'}
    # custom_user_actions = {'add', 'all', 'edit', 'delete'}

    # def has_permission(self, request, view):
    #     user = request.user
    #     action = getattr(view, 'action', None)

    #     print("DEBUG AdminOnlyForCrud -> action:", action)
    #     print("DEBUG user:", user)
    #     print("DEBUG is_authenticated:", getattr(user, "is_authenticated", None))
    #     print("DEBUG is_staff:", getattr(user, "is_staff", None))

    #     # Must be authenticated
    #     if not (user and user.is_authenticated):
    #         return False

    #     # Custom actions for any logged in user
    #     if action in self.custom_user_actions:
    #         return True

    #     # Default CRUD: staff only
    #     if action in self.admin_only_actions:
    #         return user.is_staff

    #     # Fallback
    #     return user.is_staff

    def has_permission(self, request, view):
        if view.action in {'list', 'retrieve', 'create', 'update', 'partial_update', 'destroy'}:
            return bool(request.user and request.user.is_staff)
        return bool(request.user and request.user.is_authenticated)