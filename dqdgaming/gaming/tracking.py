import uuid

from django.db import transaction
from django.utils import timezone

from gaming.models import UserDevice
from gaming.utills import get_client_ip, get_device_info


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

    device, _ = UserDevice.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            **get_device_info(request),
            "ip_address": get_client_ip(request),
            "is_deleted": False,
            "is_online": True,
            "last_seen": now,
            "login_at": now,
            "logged_out_at": None,
        },
    )
    return device


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