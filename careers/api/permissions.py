from rest_framework import permissions

class CareerPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method == "OPTIONS":
            return True

        action = getattr(view, "action", None)

        allowed = {
            "save", "my", "unsave",
            "report", "reports", "explore","unexplore","explore_mine", # ✅ add
            # AI career pathway (#24): any signed-in user, their own only -
            # the view scopes every query to request.user's profile.
            "pathway", "pathway_save",
        }

        guest = {
            "courses", "jobs", "apprenticeships", "filter", "list", "retrieve"
        }

        # ✅ Avoid confusing 403 when action can't be resolved (wrong method etc.)
        if action is None:
            return bool(request.user and request.user.is_authenticated)

        if action in allowed:
            return bool(request.user and request.user.is_authenticated)
        
        if action in guest:
            return True

        return bool(request.user and request.user.is_staff)