from rest_framework.permissions import IsAdminUser


class IsStaffUser(IsAdminUser):
    """
    Staff-only access for the admin analytics reports.

    These endpoints expose aggregate behaviour across all users, so they
    must never be public. IsAdminUser already checks `user.is_staff`.
    """

    pass
