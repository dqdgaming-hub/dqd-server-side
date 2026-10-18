"""One booking flow for games, combo packs, events and loyalty-point redemptions.

Every kind goes through the same steps:

    options(kind, target, user)        → what the booking form needs to show
    slots(kind, target, date)          → hourly start times and whether they are free
    create(user, kind, target, ...)    → validate, lock, price and save the booking

Views stay thin; all business rules live here.
"""

from dataclasses import dataclass
from datetime import date as date_type, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from gaming.models import (
    AppSetting,
    Booking,
    BookingMember,
    ComboPack,
    CustomUser,
    EventBooking,
    EventBookingMember,
    ExclusiveEvent,
    GamingItem,
    LoyaltyTransaction,
)
from gaming.utils.phone import InvalidPhone, normalize_phone


GAME = "game"
COMBO = "combo"
EVENT = "event"
LOYALTY = "loyalty"
KINDS = (GAME, COMBO, EVENT, LOYALTY)

ACTIVE_STATUSES = (Booking.Status.PENDING, Booking.Status.CONFIRMED)
MAX_MEMBERS = 20


class BookingError(Exception):
    """A user-facing reason the booking cannot be made."""

    def __init__(self, message, field="detail"):
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class Member:
    name: str
    phone: str


# ── settings ────────────────────────────────────────────────────


def open_hour():
    return int(getattr(settings, "BOOKING_OPEN_HOUR", 10))


def close_hour():
    return int(getattr(settings, "BOOKING_CLOSE_HOUR", 22))


def max_hours():
    return int(getattr(settings, "BOOKING_MAX_HOURS", 6))


def points_per_hour():
    return int(getattr(settings, "LOYALTY_POINTS_PER_HOUR", 100))


def booking_points():
    row = AppSetting.objects.filter(is_active=True).order_by("-created_at").first()
    return row.booking_loyalty_points if row else 10


# ── targets ─────────────────────────────────────────────────────


def get_target(kind, target_id):
    if kind not in KINDS:
        raise BookingError("Unknown booking type.", "kind")
    try:
        if kind in (GAME, LOYALTY):
            target = GamingItem.objects.select_related("category").get(
                pk=target_id, is_active=True, is_deleted=False
            )
            if target.maintenance_mode:
                raise BookingError("This game is under maintenance right now.")
            return target
        if kind == COMBO:
            return ComboPack.objects.prefetch_related("gaming_items").get(
                pk=target_id, is_active=True, is_deleted=False
            )
        return ExclusiveEvent.objects.get(pk=target_id, is_active=True, is_deleted=False)
    except (GamingItem.DoesNotExist, ComboPack.DoesNotExist, ExclusiveEvent.DoesNotExist, ValueError):
        raise BookingError("This item is no longer available.", "id")


def item_ids_for(kind, target):
    if kind in (GAME, LOYALTY):
        return [target.pk]
    if kind == COMBO:
        return [item.pk for item in target.gaming_items.all()]
    return []


def _capacity(kind, target):
    """(min_people, max_people) including the person booking."""
    if kind == GAME:
        return max(target.min_capacity, 1), max(target.max_capacity, 1)
    if kind == LOYALTY:
        return 1, max(target.max_capacity, 1)
    if kind == COMBO:
        return 1, max(target.max_people or 1, 1)
    seats_left = target.available_slots
    return 1, max(min(seats_left, MAX_MEMBERS + 1), 0)


def _event_start_end(event):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(event.event_date, event.start_time), tz)
    end = timezone.make_aware(datetime.combine(event.event_date, event.end_time), tz)
    return start, end


# ── step 1: options ─────────────────────────────────────────────


def options(kind, target, user):
    from gaming.utils.image_encryption import safe_image_to_data_uri

    min_people, max_people = _capacity(kind, target)
    data = {
        "kind": kind,
        "id": str(target.pk),
        "min_people": min_people,
        "max_people": max_people,
        "max_hours": max_hours(),
        "open_hour": open_hour(),
        "close_hour": close_hour(),
        "fixed_schedule": None,
    }

    if kind == GAME:
        data.update(
            title=target.name,
            subtitle=target.category.name if target.category_id else "",
            image=safe_image_to_data_uri(target.image),
            pricing="per_hour",
            price=str(target.price_per_hour),
        )
    elif kind == LOYALTY:
        balance = CustomUser.objects.filter(pk=user.pk).values_list("loyalty_points", flat=True).first() or 0
        data.update(
            title=target.name,
            subtitle="Pay with loyalty points",
            image=safe_image_to_data_uri(target.image),
            pricing="points",
            price="0",
            points_per_hour=points_per_hour(),
            points_balance=balance,
            max_hours=min(max_hours(), balance // points_per_hour()),
        )
    elif kind == COMBO:
        data.update(
            title=target.name,
            subtitle=", ".join(item.name for item in target.gaming_items.all()),
            image=safe_image_to_data_uri(target.image),
            pricing="fixed",
            price=str(target.combo_price),
            snack=target.snack_name,
            loyalty_bonus=target.loyalty_bonus,
        )
    else:
        start, end = _event_start_end(target)
        data.update(
            title=target.title,
            subtitle=target.description[:200],
            image=safe_image_to_data_uri(target.image),
            pricing="per_person",
            price=str(target.price),
            seats_left=target.available_slots,
            fixed_schedule={
                "date": target.event_date.isoformat(),
                "start_time": target.start_time.strftime("%H:%M"),
                "end_time": target.end_time.strftime("%H:%M"),
                "is_over": timezone.now() >= end,
            },
        )
    return data


# ── step 2: slots ───────────────────────────────────────────────


def _busy_ranges(item_ids, booking_date, *, exclude_pk=None):
    """(start, end) of active bookings that use any of these gaming items.

    Covers plain game bookings *and* combo bookings whose pack includes the
    item, so a combo blocks its games and vice versa.
    """
    if not item_ids:
        return []
    queryset = (
        Booking.objects.filter(
            booking_date=booking_date,
            status__in=ACTIVE_STATUSES,
            is_deleted=False,
        )
        .filter(Q(item_id__in=item_ids) | Q(combo_pack__gaming_items__in=item_ids))
        .values_list("pk", "start_time", "end_time")
        .distinct()
    )
    return [(start, end) for pk, start, end in queryset if pk != exclude_pk]


def _overlaps(ranges, start, end):
    return any(s < end and e > start for s, e in ranges)


def slots(kind, target, booking_date):
    if kind == EVENT:
        return []

    now = timezone.localtime()
    busy = _busy_ranges(item_ids_for(kind, target), booking_date)
    result = []
    for hour in range(open_hour(), close_hour()):
        start = time(hour, 0)
        end = time(hour + 1, 0) if hour + 1 < 24 else time(23, 59)
        in_future = booking_date > now.date() or (booking_date == now.date() and start > now.time())
        result.append(
            {
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
                "available": in_future and not _overlaps(busy, start, end),
            }
        )
    return result


# ── step 3: create ──────────────────────────────────────────────


def clean_members(raw_members):
    if raw_members is None:
        return []
    if not isinstance(raw_members, list):
        raise BookingError("Players must be a list.", "members")
    if len(raw_members) > MAX_MEMBERS:
        raise BookingError(f"You can add at most {MAX_MEMBERS} players.", "members")
    members = []
    for index, raw in enumerate(raw_members, start=2):
        if not isinstance(raw, dict):
            raise BookingError("Invalid player details.", "members")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise BookingError(f"Enter a name for player {index}.", "members")
        if len(name) > 150:
            raise BookingError(f"Player {index}'s name is too long.", "members")
        try:
            phone = normalize_phone(raw.get("phone")) or ""
        except InvalidPhone:
            raise BookingError(f"Player {index}'s mobile number is not valid.", "members")
        members.append(Member(name=name, phone=phone))
    return members


def _validate_people(kind, target, members):
    min_people, max_people = _capacity(kind, target)
    people = len(members) + 1
    if kind == EVENT and max_people <= 0:
        raise BookingError("This event is full.")
    if people < min_people:
        raise BookingError(
            f"This needs at least {min_people} players. Add {min_people - people} more.", "members"
        )
    if people > max_people:
        word = "seats are" if kind == EVENT else "players are"
        raise BookingError(f"Only {max_people} {word} allowed for this booking.", "members")
    return people


def _validate_time(booking_date, start_time, hours, *, limit_hours):
    if not isinstance(booking_date, date_type):
        raise BookingError("Choose a date.", "date")
    if not isinstance(start_time, time):
        raise BookingError("Choose a start time.", "start_time")
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise BookingError("Choose how many hours.", "hours")
    if hours < 1:
        raise BookingError("Book at least 1 hour.", "hours")
    if hours > limit_hours:
        raise BookingError(f"You can book at most {limit_hours} hour{'s' if limit_hours != 1 else ''}.", "hours")

    now = timezone.localtime()
    if booking_date < now.date():
        raise BookingError("This date has passed. Pick today or later.", "date")
    if booking_date > now.date() + timedelta(days=int(getattr(settings, "BOOKING_MAX_DAYS_AHEAD", 60))):
        raise BookingError("That date is too far ahead.", "date")

    start = start_time.replace(second=0, microsecond=0, tzinfo=None)
    if start.hour < open_hour():
        raise BookingError(f"We open at {open_hour()}:00.", "start_time")
    if booking_date == now.date() and start <= now.time().replace(tzinfo=None):
        raise BookingError("This time has passed. Pick a later time.", "start_time")

    end_dt = datetime.combine(booking_date, start) + timedelta(hours=hours)
    closing = datetime.combine(booking_date, time(0)) + timedelta(hours=close_hour())
    if end_dt > closing:
        raise BookingError(f"We close at {close_hour()}:00. Pick an earlier time or fewer hours.", "hours")
    return start, end_dt.time(), hours


def _lock_items(item_ids):
    # Fixed order avoids deadlocks when two requests lock overlapping sets.
    list(GamingItem.objects.select_for_update().filter(pk__in=item_ids).order_by("pk").values_list("pk", flat=True))


@transaction.atomic
def create(user, kind, target, *, booking_date=None, start_time=None, hours=1, members=None, notes=""):
    members = clean_members(members)
    notes = str(notes or "").strip()[:500]

    if kind == EVENT:
        return _create_event_booking(user, target, members, notes)

    limit = max_hours()
    if kind == LOYALTY:
        balance = CustomUser.objects.filter(pk=user.pk).values_list("loyalty_points", flat=True).first() or 0
        limit = min(limit, balance // points_per_hour())
        if limit < 1:
            raise BookingError(f"You need at least {points_per_hour()} points for a free hour.", "hours")

    start, end, hours = _validate_time(booking_date, start_time, hours, limit_hours=limit)
    people = _validate_people(kind, target, members)

    item_ids = item_ids_for(kind, target)
    _lock_items(item_ids)
    if _overlaps(_busy_ranges(item_ids, booking_date), start, end):
        raise BookingError("Sorry, that time was just booked. Please pick another slot.", "start_time")

    common = dict(
        user=user,
        booking_date=booking_date,
        start_time=start,
        end_time=end,
        total_hours=Decimal(hours),
        notes=notes,
        status=Booking.Status.PENDING,
    )

    if kind == GAME:
        subtotal = target.price_per_hour * hours
        booking = Booking.objects.create(
            **common,
            item=target,
            subtotal=subtotal,
            total_amount=subtotal,
            loyalty_points_earned=booking_points(),
        )
    elif kind == COMBO:
        booking = Booking.objects.create(
            **common,
            combo_pack=target,
            subtotal=target.combo_price,
            total_amount=target.combo_price,
            loyalty_points_earned=target.loyalty_bonus or 0,
        )
    else:  # LOYALTY
        cost = hours * points_per_hour()
        locked_user = CustomUser.objects.select_for_update().get(pk=user.pk)
        if locked_user.loyalty_points < cost:
            raise BookingError(f"You need {cost} points but have {locked_user.loyalty_points}.", "hours")
        booking = Booking.objects.create(
            **common,
            item=target,
            subtotal=Decimal("0"),
            total_amount=Decimal("0"),
        )
        CustomUser.objects.filter(pk=user.pk).update(loyalty_points=F("loyalty_points") - cost)
        LoyaltyTransaction.objects.create(
            user=user,
            booking=booking,
            points=-cost,
            transaction_type=LoyaltyTransaction.TransactionType.REDEEMED,
            description=f"Redeemed {cost} points for {hours} hour(s) on {target.name}",
        )

    BookingMember.objects.bulk_create(
        [BookingMember(booking=booking, name=m.name, phone=m.phone) for m in members]
    )
    booking.people = people
    return booking


def _create_event_booking(user, event, members, notes):
    event = ExclusiveEvent.objects.select_for_update().get(pk=event.pk)
    start, end = _event_start_end(event)
    if timezone.now() >= end:
        raise BookingError("This event has already finished.")
    if EventBooking.objects.filter(event=event, user=user).exclude(
        status__in=[EventBooking.Status.CANCELLED, EventBooking.Status.REJECTED]
    ).exists():
        raise BookingError("You have already booked this event. Add guests by cancelling and booking again.")

    people = _validate_people(EVENT, event, members)

    booking = EventBooking.objects.create(
        event=event,
        user=user,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        amount_paid=event.price * people,
        status=EventBooking.Status.PENDING,
        notes=notes,
    )
    EventBookingMember.objects.bulk_create(
        [EventBookingMember(event_booking=booking, name=m.name, phone=m.phone) for m in members]
    )
    booking.people = people
    return booking


# ── response shape ──────────────────────────────────────────────


def summary(kind, booking):
    if kind == EVENT:
        event = booking.event
        return {
            "kind": kind,
            "id": str(booking.pk),
            "booking_id": booking.booking_id,
            "title": event.title,
            "date": event.event_date.isoformat(),
            "start_time": event.start_time.strftime("%H:%M"),
            "end_time": event.end_time.strftime("%H:%M"),
            "people": getattr(booking, "people", 1),
            "total_amount": str(booking.amount_paid),
            "status": booking.status,
        }
    title = booking.combo_pack.name if booking.combo_pack_id else booking.item.name
    return {
        "kind": kind,
        "id": str(booking.pk),
        "booking_id": booking.booking_id,
        "title": title,
        "date": booking.booking_date.isoformat(),
        "start_time": booking.start_time.strftime("%H:%M"),
        "end_time": booking.end_time.strftime("%H:%M"),
        "hours": int(booking.total_hours),
        "people": getattr(booking, "people", 1),
        "total_amount": str(booking.total_amount),
        "points_used": int(booking.total_hours) * points_per_hour() if kind == LOYALTY else 0,
        "status": booking.status,
    }
