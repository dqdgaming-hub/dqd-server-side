"""WhatsApp messages to customers (Click-to-Chat links).

Messages are sent only for:
    • account created by an admin (and an admin password reset)
    • a booking added by an admin (game, combo, event)
    • a booking confirmed / approved (game, combo, loyalty, event)

The server builds a prefilled ``https://wa.me/<number>?text=...`` link; the
admin panel shows the message for review and one tap opens WhatsApp to send
it. To send automatically later, replace ``generate_whatsapp_url`` with a
WhatsApp Business Cloud API call — the callers don't change.
"""

import logging
from urllib.parse import quote

from django.conf import settings

from gaming.utils.phone import InvalidPhone, normalize_phone


logger = logging.getLogger(__name__)

LABEL_WIDTH = 10


def generate_whatsapp_url(receiver_number, message):
    """Return a Click-to-Chat URL, or ``None`` when the number is unusable."""
    try:
        receiver = normalize_phone(receiver_number)
    except InvalidPhone:
        receiver = None

    if not receiver or not message:
        return None

    return f"https://wa.me/{receiver}?text={quote(message)}"


# ── formatting helpers ──────────────────────────────────────────


def _venue():
    return getattr(settings, "WHATSAPP_BUSINESS_NAME", "") or "DQD Gaming"


def _site():
    return getattr(settings, "FRONTEND_URL", "").rstrip("/")


def _pretty_number(number):
    try:
        digits = normalize_phone(number)
    except InvalidPhone:
        return ""
    if not digits:
        return ""
    if len(digits) == 12 and digits.startswith("91"):
        return f"+91 {digits[2:7]} {digits[7:]}"
    return f"+{digits}"


def _time(value):
    return value.strftime("%I:%M %p").lstrip("0") if value else "-"


def _date(value):
    return value.strftime("%a, %d %b %Y") if value else "-"


def _money(value):
    return f"Rs. {float(value or 0):,.2f}"


def _hours(value):
    hours = float(value or 0)
    text = f"{hours:g}"
    return f"{text} hr" if hours == 1 else f"{text} hrs"


def _table(rows):
    """Aligned ``label : value`` block, sent as WhatsApp monospace."""
    lines = [f"{label.ljust(LABEL_WIDTH)}: {value}" for label, value in rows if value not in (None, "")]
    return "```\n" + "\n".join(lines) + "\n```"


def _people(first_name, members):
    names = [f"1. {first_name} (you)"] + [
        f"{index}. {member.name}" for index, member in enumerate(members, start=2)
    ]
    return "\n".join(names)


def _footer():
    lines = []
    if _site():
        lines.append(f"My bookings: {_site()}/user/bookings")
    contact = _pretty_number(getattr(settings, "WHATSAPP_SENDER_NUMBER", ""))
    address = getattr(settings, "VENUE_ADDRESS", "")
    if address:
        lines.append(f"Address: {address}")
    if contact:
        lines.append(f"Questions? WhatsApp us on {contact}")
    lines.append(f"- Team {_venue()}")
    return "\n".join(lines)


def _join(*parts):
    return "\n\n".join(part for part in parts if part)


# ── account ─────────────────────────────────────────────────────


def account_credentials_message(user, password, *, is_new=True):
    heading = (
        f"Welcome to *{_venue()}*! Your account has been created."
        if is_new
        else f"Your *{_venue()}* password has been reset."
    )
    details = _table([
        ("Name", user.full_name),
        ("Mobile", _pretty_number(user.phone)),
        ("Email", user.email),
        ("Password", password),
        ("Sign in", f"{_site()}/sign-in" if _site() else ""),
    ])
    return _join(
        f"Hi {user.first_name or 'there'} 👋",
        heading,
        "*Your login details*\n" + details,
        "Sign in with your mobile number and this password, then change the password from Profile settings. "
        "Please don't share it with anyone.",
        _footer(),
    )


# ── game / combo / loyalty bookings ─────────────────────────────


def booking_message(booking, *, added_by_admin=False):
    members = list(booking.members.all())
    is_combo = bool(booking.combo_pack_id)
    # .all() so a prefetch on list pages is reused (no extra query per row)
    paid_with_points = bool(
        booking.item_id
        and not booking.total_amount
        and any(t.points < 0 for t in booking.loyalty_transactions.all())
    )

    if booking.status == "confirmed":
        headline = "✅ Your booking is *confirmed*!"
        next_step = "Show the QR code from My bookings at the counter when you arrive. Please come 10 minutes early."
    else:
        headline = (
            "📝 We've booked a slot for you." if added_by_admin else "📝 We received your booking."
        )
        next_step = "We'll send another message once it is confirmed."

    kind = "Combo pack" if is_combo else ("Game (loyalty points)" if paid_with_points else "Game")
    rows = [
        ("Booking ID", booking.booking_id),
        ("Type", kind),
        ("Combo" if is_combo else "Game", booking.combo_pack.name if is_combo else (booking.item.name if booking.item_id else "-")),
    ]
    if is_combo and booking.combo_pack.snack_name:
        rows.append(("Includes", booking.combo_pack.snack_name))
    rows += [
        ("Date", _date(booking.booking_date)),
        ("Time", f"{_time(booking.start_time)} - {_time(booking.end_time)}"),
        ("Duration", _hours(booking.total_hours)),
        ("Players", str(len(members) + 1)),
        ("Amount", "Paid with points" if paid_with_points else _money(booking.total_amount)),
    ]
    if not paid_with_points:
        rows.append(("Payment", (booking.payment_status or "pending").capitalize()))
    if booking.discount_amount:
        rows.append(("Discount", _money(booking.discount_amount)))
    if booking.awarded_loyalty_points:
        rows.append(("Points", f"+{booking.awarded_loyalty_points} on completion"))
    if booking.is_happy_hour:
        rows.append(("Offer", "Happy hour"))

    customer_first = booking.user.first_name if booking.user_id else (booking.guest_name or "Guest")
    return _join(
        f"Hi {customer_first} 👋",
        headline,
        "*Booking details*\n" + _table(rows),
        "*Players*\n" + _people(customer_first, members),
        f"Note: {booking.notes}" if booking.notes else "",
        next_step,
        _footer(),
    )


# ── events ──────────────────────────────────────────────────────


def event_booking_message(booking, *, added_by_admin=False):
    event = booking.event
    members = list(booking.members.all())
    if booking.status == "approved":
        headline = f"✅ Your seat for *{event.title}* is *confirmed*!"
        next_step = "Show the QR code from My bookings at the entrance."
    else:
        headline = (
            f"📝 We've registered you for *{event.title}*."
            if added_by_admin
            else f"📝 We received your registration for *{event.title}*."
        )
        next_step = "We'll send another message once it is confirmed."

    rows = [
        ("Booking ID", booking.booking_id),
        ("Event", event.title),
        ("Date", _date(event.event_date)),
        ("Time", f"{_time(event.start_time)} - {_time(event.end_time)}"),
        ("Seats", str(len(members) + 1)),
        ("Amount", _money(booking.amount_paid)),
    ]
    first = (booking.full_name or "there").split(" ")[0]
    return _join(
        f"Hi {first} 👋",
        headline,
        "*Event details*\n" + _table(rows),
        "*Guests*\n" + _people(first, members),
        next_step,
        _footer(),
    )


# ── URL helpers used by the views (never raise) ─────────────────


def booking_whatsapp_url(booking, *, added_by_admin=False):
    try:
        return generate_whatsapp_url(
            booking.customer_phone, booking_message(booking, added_by_admin=added_by_admin)
        )
    except Exception:
        logger.exception("Could not build WhatsApp link for booking %s", booking.pk)
        return None


def event_booking_whatsapp_url(booking, *, added_by_admin=False):
    phone = booking.phone or (booking.user.phone if booking.user_id else None)
    try:
        return generate_whatsapp_url(phone, event_booking_message(booking, added_by_admin=added_by_admin))
    except Exception:
        logger.exception("Could not build WhatsApp link for event booking %s", booking.pk)
        return None
