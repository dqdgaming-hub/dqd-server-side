import logging
import uuid

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from gaming.models import LoginActivity, UserDevice
from gaming.utills import get_client_ip, get_device_info


logger = logging.getLogger(__name__)

DEVICE_HEADER = "HTTP_X_DEVICE_ID"
MAX_DEVICE_ID_LENGTH = 45


def parse_device_id(request):
    """Return the UUID from ``X-Device-ID`` or ``None`` when it is invalid."""
    meta = getattr(request, "META", None)
    if not meta:
        return None

    raw_value = meta.get(DEVICE_HEADER, "")
    if not isinstance(raw_value, str):
        return None

    raw_value = raw_value.strip()
    if not raw_value or len(raw_value) > MAX_DEVICE_ID_LENGTH:
        return None

    try:
        return uuid.UUID(raw_value)
    except (AttributeError, TypeError, ValueError):
        return None


@transaction.atomic
def register_device(request, user):
    """Create or refresh the authenticated user's current device record."""
    device_id = parse_device_id(request) or uuid.uuid4()
    now = timezone.now()
    ip_address = get_client_ip(request)

    device, created = UserDevice.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            **get_device_info(request),
            "ip_address": ip_address,
            "is_deleted": False,
            "is_online": True,
            "last_seen": now,
            "login_at": now,
            "logged_out_at": None,
        },
        create_defaults={
            **get_device_info(request),
            "ip_address": ip_address,
            "first_ip_address": ip_address,
            "last_seen": now,
            "login_at": now,
        },
    )
    return device


def touch_device(request, user, interval_seconds):
    """Refresh last_seen / latest IP for the request's device.

    Called on authenticated API requests; the cache gate keeps it to at most
    one UPDATE per device per interval.
    """
    device_id = parse_device_id(request)
    if not getattr(user, "is_authenticated", False) or device_id is None:
        return

    if not cache.add(f"device-touch:{user.pk}:{device_id}", 1, interval_seconds):
        return

    now = timezone.now()
    updates = {"last_seen": now}
    ip_address = get_client_ip(request)
    if ip_address:
        updates["ip_address"] = ip_address
    try:
        UserDevice.objects.filter(
            user=user,
            device_id=device_id,
            is_deleted=False,
            is_online=True,
        ).update(**updates)
    except Exception:
        logger.exception("Could not refresh device activity")


def record_login_activity(request, event, *, user=None, identifier="", detail="", device_id=None):
    """Save an audit row. Never raises: tracking must not break sign-in."""
    try:
        info = get_device_info(request)
        LoginActivity.objects.create(
            user=user if getattr(user, "pk", None) else None,
            identifier=str(identifier or "")[:254],
            event=event,
            ip_address=get_client_ip(request),
            device_id=device_id or parse_device_id(request),
            device_name=info["device_name"],
            device_type=info["device_type"],
            browser=info["browser"],
            operating_system=info["operating_system"],
            user_agent=info["user_agent"],
            detail=str(detail or "")[:255],
        )
    except Exception:
        logger.exception("Could not record login activity (%s)", event)


def mark_current_device_offline(request):
    """Mark only the authenticated user's declared current device offline."""
    user = getattr(request, "user", None)
    device_id = parse_device_id(request)
    if not getattr(user, "is_authenticated", False) or device_id is None:
        return 0

    now = timezone.now()
    return UserDevice.objects.filter(
        user=user,
        device_id=device_id,
        is_deleted=False,
    ).update(
        is_online=False,
        last_seen=now,
        logged_out_at=now,
    )
