from rest_framework.permissions import BasePermission

class HasActiveSubscription(BasePermission):
    message = "Active subscription required."

    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_staff:
            return True

        billing = getattr(user, "billing", None)
        return bool(billing and billing.is_active)
