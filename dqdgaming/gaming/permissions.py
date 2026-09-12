# from rest_framework.permissions import BasePermission


# class IsAdminUserRole(BasePermission):
#     message = "Only administrators can access this endpoint."

#     def has_permission(self, request, view):
#         user = request.user

#         return bool(
#             user
#             and user.is_authenticated
#             and (user.is_superuser or user.is_staff or user.role == "admin")
#         )




from rest_framework.permissions import BasePermission


class IsAdminUserRole(BasePermission):
    """Allow superusers, staff users, and users with the admin role."""

    message = "Only administrators can access this endpoint."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return False

        return bool(
            getattr(user, "is_superuser", False)
            or getattr(user, "is_staff", False)
            or getattr(user, "role", None) == "admin"
        )