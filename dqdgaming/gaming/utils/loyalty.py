from django.db import transaction
from django.db.models import F
from gaming.models import Booking, LoyaltyTransaction


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

    if not booking.user:
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

    booking.user.loyalty_points = F("loyalty_points") + points
    booking.user.save(update_fields=["loyalty_points"])

    return loyalty_transaction
