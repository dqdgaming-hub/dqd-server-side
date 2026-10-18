import ipaddress
import json
import re

from django.conf import settings
from user_agents import parse


UNKNOWN = "Unknown"
MAX_USER_AGENT_LENGTH = 1000
MAX_CLIENT_INFO_LENGTH = 2000
CLIENT_INFO_HEADER = "HTTP_X_CLIENT_INFO"

_SAFE_TEXT_RE = re.compile(r"[^\w .,:;()/+\-@#]")


def _clean(value, max_length):
    """Return a bounded printable string suitable for database storage."""
    value = "" if value is None else str(value)
    value = "".join(character for character in value if character.isprintable())
    value = value.strip()
    return value[:max_length] if value else UNKNOWN


def _clean_optional(value, max_length):
    """Like ``_clean`` but returns "" for missing values and strips odd characters."""
    if value is None:
        return ""
    value = _SAFE_TEXT_RE.sub("", str(value)).strip()
    return value[:max_length]


def _clean_user_agent(value):
    """Bound untrusted header content while preserving an empty user agent."""
    value = "" if value is None else str(value)
    return "".join(
        character
        for character in value[:MAX_USER_AGENT_LENGTH]
        if character.isprintable()
    )


# ── IP address ─────────────────────────────────────────────────


def _parse_ip(raw):
    try:
        return str(ipaddress.ip_address(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def get_client_ip(request):
    """Return the real client IP.

    Directly connected (``USE_X_FORWARDED_FOR=False``): ``REMOTE_ADDR``.

    Behind ``NUM_PROXIES`` trusted proxies: the address added by the outermost
    trusted proxy, counted from the *right* of ``X-Forwarded-For``. The left
    part of that header is supplied by the client and can be forged, so it is
    never trusted. ``X-Real-IP`` (nginx) is used when present instead.
    """
    meta = getattr(request, "META", {})
    remote_addr = meta.get("REMOTE_ADDR", "")
    if not isinstance(remote_addr, str):
        return None

    if not getattr(settings, "USE_X_FORWARDED_FOR", False):
        return _parse_ip(remote_addr)

    real_ip = meta.get("HTTP_X_REAL_IP", "")
    if isinstance(real_ip, str) and real_ip.strip() and getattr(settings, "TRUST_X_REAL_IP", False):
        return _parse_ip(real_ip)

    forwarded_for = meta.get("HTTP_X_FORWARDED_FOR", "")
    if not isinstance(forwarded_for, str) or not forwarded_for.strip():
        return _parse_ip(remote_addr)

    addresses = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    num_proxies = max(int(getattr(settings, "NUM_PROXIES_FOR_IP", 1) or 1), 1)
    index = -num_proxies if len(addresses) >= num_proxies else 0
    return _parse_ip(addresses[index])


# ── Client hints (sent by the frontend in X-Client-Info) ───────


def get_client_hints(request):
    """Parse the JSON the browser sends about itself (bounded and sanitized).

    Browsers freeze parts of the User-Agent string (Chrome always reports
    "Windows 10" and phone model "K"), so the frontend reads the real values
    from ``navigator.userAgentData`` and screen/locale APIs and sends them.
    Everything here is client supplied: use it for display, never for security
    decisions.
    """
    meta = getattr(request, "META", {})
    raw = meta.get(CLIENT_INFO_HEADER, "")
    if not isinstance(raw, str) or not raw or len(raw) > MAX_CLIENT_INFO_LENGTH:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}

    brands = data.get("brands")
    browser = ""
    browser_version = ""
    if isinstance(brands, list):
        # Prefer a real brand over "Chromium" / "Not A Brand" placeholders.
        candidates = [
            b for b in brands
            if isinstance(b, dict) and "not" not in str(b.get("brand", "")).lower()
        ]
        candidates.sort(key=lambda b: str(b.get("brand", "")).lower() == "chromium")
        if candidates:
            browser = _clean_optional(candidates[0].get("brand"), 60)
            browser_version = _clean_optional(candidates[0].get("version"), 30)

    return {
        "platform": _clean_optional(data.get("platform"), 40),
        "platform_version": _clean_optional(data.get("platformVersion"), 30),
        "model": _clean_optional(data.get("model"), 100),
        "mobile": data.get("mobile") is True,
        "browser": browser,
        "browser_version": browser_version,
        "screen": _clean_optional(data.get("screen"), 20),
        "timezone": _clean_optional(data.get("timezone"), 64),
        "language": _clean_optional(data.get("language"), 35),
    }


def _hinted_os(platform, platform_version):
    if not platform:
        return ""
    major = platform_version.split(".", 1)[0] if platform_version else ""
    if platform == "Windows" and major.isdigit():
        # Client-hint platformVersion 13+ means Windows 11.
        return "Windows 11" if int(major) >= 13 else "Windows 10" if int(major) >= 1 else "Windows 7/8"
    if platform == "macOS" and platform_version:
        return f"macOS {platform_version}"
    if platform_version:
        return f"{platform} {platform_version}"
    return platform


# ── Device info ────────────────────────────────────────────────


def get_device_info(request):
    """Return bounded, normalized device metadata.

    Uses the User-Agent header, improved with browser client hints when the
    frontend sends them.
    """
    meta = getattr(request, "META", {})
    user_agent = _clean_user_agent(meta.get("HTTP_USER_AGENT", ""))
    hints = get_client_hints(request)

    try:
        parsed = parse(user_agent)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        browser = operating_system = device_name = UNKNOWN
        device_type = "other"
    else:
        browser = parsed.browser.family
        if parsed.browser.version_string:
            browser = f"{browser} {parsed.browser.version_string}"

        operating_system = parsed.os.family
        if parsed.os.version_string:
            operating_system = f"{operating_system} {parsed.os.version_string}"

        device_name = parsed.device.family
        if parsed.device.brand and parsed.device.model and parsed.device.model not in device_name:
            device_name = f"{parsed.device.brand} {parsed.device.model}"
        if not device_name or device_name in ("Other", "K"):
            if parsed.is_mobile:
                device_name = "Mobile"
            elif parsed.is_tablet:
                device_name = "Tablet"
            elif parsed.is_pc:
                device_name = "Desktop"
            elif parsed.is_bot:
                device_name = "Bot"

        if parsed.is_bot:
            device_type = "bot"
        elif parsed.is_tablet:
            device_type = "tablet"
        elif parsed.is_mobile:
            device_type = "mobile"
        elif parsed.is_pc:
            device_type = "desktop"
        else:
            device_type = "other"

    if hints.get("browser"):
        browser = f"{hints['browser']} {hints['browser_version']}".strip()
    hinted_os = _hinted_os(hints.get("platform", ""), hints.get("platform_version", ""))
    if hinted_os:
        operating_system = hinted_os
    if hints.get("model"):
        device_name = hints["model"]
    if hints.get("mobile") and device_type in ("desktop", "other"):
        device_type = "mobile"

    return {
        "browser": _clean(browser, 150),
        "operating_system": _clean(operating_system, 150),
        "device_name": _clean(device_name, 255),
        "device_type": device_type,
        "user_agent": user_agent,
        "screen_resolution": hints.get("screen", ""),
        "time_zone": hints.get("timezone", ""),
        "language": hints.get("language", "") or _clean_optional(
            str(meta.get("HTTP_ACCEPT_LANGUAGE", "")).split(",", 1)[0], 35
        ),
    }
