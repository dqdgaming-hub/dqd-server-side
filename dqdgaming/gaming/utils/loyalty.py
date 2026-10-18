from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Greatest

from gaming.models import Booking, CustomUser, LoyaltyTransaction


CREDIT_TYPES = (
    LoyaltyTransaction.TransactionType.EARNED,
    LoyaltyTransaction.TransactionType.COMBO_BONUS,
    LoyaltyTransaction.TransactionType.ADMIN_GRANT,
)


@transaction.atomic
def award_booking_loyalty_points(booking, admin_user=None):
    """
    Save booking loyalty points to the user's account.

    Works for:
    - combo pack loyalty_bonus
    - admin manual loyalty points
    - normal booking loyalty_points_earned

    Safe to call more than once for the same booking.
    """

    booking = (
        Booking.objects.select_related("user", "combo_pack")
        .select_for_update(of=("self",))
        .get(pk=booking.pk)
    )

    if not booking.user or booking.status == Booking.Status.CANCELLED:
        return None

    points = booking.awarded_loyalty_points

    if points <= 0 and booking.combo_pack and not booking.use_manual_loyalty_points:
        points = booking.combo_pack.loyalty_bonus
        booking.loyalty_points_earned = points
        booking.save(update_fields=["loyalty_points_earned"])

    if points <= 0:
        return None

    existing_transaction = LoyaltyTransaction.objects.filter(
        booking=booking,
        transaction_type__in=CREDIT_TYPES,
    ).first()

    if existing_transaction:
        return existing_transaction

    transaction_type = LoyaltyTransaction.TransactionType.EARNED
    granted_by = None

    if booking.use_manual_loyalty_points:
        transaction_type = LoyaltyTransaction.TransactionType.ADMIN_GRANT
        granted_by = admin_user
    elif booking.combo_pack:
        transaction_type = LoyaltyTransaction.TransactionType.COMBO_BONUS

    loyalty_transaction = LoyaltyTransaction.objects.create(
        user=booking.user,
        booking=booking,
        points=points,
        transaction_type=transaction_type,
        granted_by=granted_by,
        description=f"Booking {booking.booking_id}",
    )

    CustomUser.objects.filter(pk=booking.user_id).update(
        loyalty_points=F("loyalty_points") + points
    )

    return loyalty_transaction


@transaction.atomic
def reverse_booking_loyalty_points(booking, reason="cancelled"):
    """Undo loyalty effects of a cancelled booking (idempotent).

    - Points *earned* for the booking are taken back.
    - Points *spent* to redeem the booking are refunded.
    Returns the net change applied to the user's balance.
    """
    if not booking.user_id:
        return 0

    # Serialize concurrent cancels for the same booking.
    Booking.objects.select_for_update(of=("self",)).filter(pk=booking.pk).first()

    totals = LoyaltyTransaction.objects.filter(booking_id=booking.pk).aggregate(net=Sum("points"))
    net = totals["net"] or 0
    if net == 0:
        return 0

    LoyaltyTransaction.objects.create(
        user_id=booking.user_id,
        booking_id=booking.pk,
        points=-net,
        transaction_type=(
            LoyaltyTransaction.TransactionType.REDEEMED
            if net > 0
            else LoyaltyTransaction.TransactionType.ADMIN_GRANT
        ),
        description=f"Booking {booking.booking_id} {reason}: "
        + ("points reversed" if net > 0 else "redeemed points refunded"),
    )
    CustomUser.objects.filter(pk=booking.user_id).update(
        loyalty_points=Greatest(F("loyalty_points") - net, 0)
    )
    return -net
