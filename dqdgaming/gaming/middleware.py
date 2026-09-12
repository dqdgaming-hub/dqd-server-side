from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from gaming.models import UserDevice
from gaming.tracking import parse_device_id


DEFAULT_ACTIVITY_INTERVAL_SECONDS = 120


def get_activity_interval():
    """Return a safe, configurable interval between device write operations."""
    value = getattr(
        settings,
        "DEVICE_ACTIVITY_INTERVAL_SECONDS",
        DEFAULT_ACTIVITY_INTERVAL_SECONDS,
    )
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return DEFAULT_ACTIVITY_INTERVAL_SECONDS


class UpdateLastSeenMiddleware:
    """Refresh session-authenticated device activity without writing per request.

    Keep this after ``AuthenticationMiddleware``. JWT-authenticated DRF views
    should also use ``DeviceActivityMixin`` because DRF authenticates inside
    the view lifecycle.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self.touch(request)
        return self.get_response(request)

    @classmethod
    def touch(cls, request):
        user = getattr(request, "user", None)
        device_id = parse_device_id(request)
        if not getattr(user, "is_authenticated", False) or device_id is None:
            return

        now = timezone.now()
        cutoff = now - timedelta(seconds=get_activity_interval())
        UserDevice.objects.filter(
            user=user,
            device_id=device_id,
            is_deleted=False,
            is_online=True,
            last_seen__lt=cutoff,
        ).update(last_seen=now)


class DeviceActivityMixin:
    """Use on JWT-protected DRF API views to refresh device activity."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        UpdateLastSeenMiddleware.touch(request)