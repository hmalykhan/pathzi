from rest_framework.permissions import BasePermission

class HasActiveSubscription(BasePermission):
    message = "Active subscription required."

    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # For real production you might want staff to always bypass subscription.
        # For now, comment this out so you can test the 5-career limit:
        # if user.is_staff:
            # return True

        billing = getattr(user, "billing", None)
        return bool(billing and billing.is_active)
