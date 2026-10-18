import logging
import re
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from gaming.models import UserDevice
from gaming.tracking import parse_device_id


DEFAULT_ACTIVITY_INTERVAL_SECONDS = 120

request_logger = logging.getLogger("gaming.requests")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class RequestLogMiddleware:
    """Tag each request with an ID and log errors / slow requests.

    Reuses a sane ``X-Request-ID`` from the reverse proxy or load balancer so
    one ID follows a request across nginx, gunicorn and the app logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.slow_ms = int(getattr(settings, "SLOW_REQUEST_MS", 1000))

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        request.request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        started = time.monotonic()

        response = self.get_response(request)

        duration_ms = (time.monotonic() - started) * 1000
        response["X-Request-ID"] = request.request_id

        if response.status_code >= 500:
            level = logging.ERROR
        elif duration_ms >= self.slow_ms or response.status_code in (401, 403, 429):
            level = logging.WARNING
        else:
            level = logging.DEBUG

        request_logger.log(
            level,
            "%s %s -> %s in %.0fms [request_id=%s]",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            request.request_id,
        )
        return response


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