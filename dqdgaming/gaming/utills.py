import ipaddress

from django.conf import settings
from user_agents import parse


UNKNOWN = "Unknown"
MAX_USER_AGENT_LENGTH = 1000


def _clean(value, max_length):
    """Return a bounded printable string suitable for database storage."""
    value = "" if value is None else str(value)
    value = "".join(character for character in value if character.isprintable())
    value = value.strip()
    return value[:max_length] if value else UNKNOWN


def _clean_user_agent(value):
    """Bound untrusted header content while preserving an empty user agent."""
    value = "" if value is None else str(value)
    return "".join(
        character
        for character in value[:MAX_USER_AGENT_LENGTH]
        if character.isprintable()
    )


def get_client_ip(request):
    """Return the client IP, trusting forwarded headers only behind a proxy.

    Set ``USE_X_FORWARDED_FOR=True`` only when the reverse proxy overwrites
    incoming ``X-Forwarded-For`` headers before forwarding a request.
    """
    meta = getattr(request, "META", {})
    raw_ip = meta.get("REMOTE_ADDR", "")
    if not isinstance(raw_ip, str):
        return None

    if getattr(settings, "USE_X_FORWARDED_FOR", False):
        forwarded_for = meta.get("HTTP_X_FORWARDED_FOR", "")
        if isinstance(forwarded_for, str) and forwarded_for:
            raw_ip = forwarded_for.split(",", 1)[0].strip()

    try:
        return str(ipaddress.ip_address(raw_ip))
    except (TypeError, ValueError):
        return None


def get_device_info(request):
    """Return bounded, normalized device metadata from the User-Agent header."""
    meta = getattr(request, "META", {})
    user_agent = _clean_user_agent(meta.get("HTTP_USER_AGENT", ""))

    try:
        parsed = parse(user_agent)
    except (TypeError, ValueError):
        return {
            "browser": UNKNOWN,
            "operating_system": UNKNOWN,
            "device_name": UNKNOWN,
            "device_type": "other",
            "user_agent": user_agent,
        }

    browser = parsed.browser.family
    if parsed.browser.version_string:
        browser = f"{browser} {parsed.browser.version_string}"

    operating_system = parsed.os.family
    if parsed.os.version_string:
        operating_system = f"{operating_system} {parsed.os.version_string}"

    device_name = parsed.device.family
    if not device_name or device_name == "Other":
        if parsed.is_mobile:
            device_name = "Mobile"
        elif parsed.is_tablet:
            device_name = "Tablet"
        elif parsed.is_pc:
            device_name = "Desktop"
        elif parsed.is_bot:
            device_name = "Bot"

    if parsed.is_mobile:
        device_type = "mobile"
    elif parsed.is_tablet:
        device_type = "tablet"
    elif parsed.is_pc:
        device_type = "desktop"
    elif parsed.is_bot:
        device_type = "bot"
    else:
        device_type = "other"

    return {
        "browser": _clean(browser, 150),
        "operating_system": _clean(operating_system, 150),
        "device_name": _clean(device_name, 255),
        "device_type": device_type,
        "user_agent": user_agent,
    }