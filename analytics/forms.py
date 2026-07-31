from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class StaffAuthenticationForm(AuthenticationForm):
    """Login form for the analytics dashboard — only staff accounts may sign in."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(
                "This account doesn't have dashboard access.",
                code="no_staff",
            )
