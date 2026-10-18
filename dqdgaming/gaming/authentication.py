from rest_framework_simplejwt.authentication import JWTAuthentication

from gaming.middleware import get_activity_interval
from gaming.tracking import touch_device


class TrackedJWTAuthentication(JWTAuthentication):
    """JWT auth that also refreshes the device's last-seen time and IP."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            touch_device(request, result[0], get_activity_interval())
        return result
