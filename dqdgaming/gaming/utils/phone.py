import re

from django.conf import settings


_STRIP_RE = re.compile(r"[\s\-().]")
_DIGITS_RE = re.compile(r"^\d{8,15}$")


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw, *, required=False):
    """Return a phone number as international digits (no ``+``), e.g. ``919876543210``.

    A bare 10-digit local number gets ``DEFAULT_PHONE_COUNTRY_CODE`` prefixed so
    the same person always maps to the same stored value (used for login and
    WhatsApp links). Returns ``None`` for empty input unless ``required``.
    """
    value = _STRIP_RE.sub("", str(raw or "").strip())

    if not value:
        if required:
            raise InvalidPhone("Mobile number is required.")
        return None

    if value.startswith("+"):
        value = value[1:]
    elif value.startswith("00"):
        value = value[2:]
    else:
        local_length = getattr(settings, "LOCAL_PHONE_LENGTH", 10)
        country_code = getattr(settings, "DEFAULT_PHONE_COUNTRY_CODE", "")
        value = value.lstrip("0") if len(value) == local_length + 1 else value
        if len(value) == local_length and country_code:
            value = f"{country_code}{value}"

    if not _DIGITS_RE.match(value):
        raise InvalidPhone("Enter a valid mobile number.")

    return value


def phone_lookup_values(raw):
    """Values a stored phone may have for this input (normalized + legacy raw)."""
    values = set()
    try:
        normalized = normalize_phone(raw)
    except InvalidPhone:
        normalized = None
    if normalized:
        values.add(normalized)
        local_length = getattr(settings, "LOCAL_PHONE_LENGTH", 10)
        # Legacy rows were stored without the country code.
        values.add(normalized[-local_length:])
        values.add(f"+{normalized}")
    return values
