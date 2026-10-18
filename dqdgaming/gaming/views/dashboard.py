"""User dashboard view."""

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.middleware import DeviceActivityMixin
from gaming.models import (
    Booking,
    ComboPack,
    EventBooking,
    ExclusiveEvent,
    GamingItem,
    LoyaltyTransaction,
    SpinnerReward,
    SpinnerSpin,
)
from gaming.serializers import (
    BookingSerializer,
    ComboPackSerializer,
    EventBookingSerializer,
    ExclusiveEventSerializer,
    GameSerializer,
    LoyaltyTransactionSerializer,
    SpinnerSpinSerializer,
    UserDetailsSerializer,
    UserSpinnerRewardSerializer,
)


class UserDashboardAPIView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        games = GamingItem.objects.filter(
            is_active=True,
            is_deleted=False,
            maintenance_mode=False,
        ).select_related("category")

        recent_bookings = (
            Booking.objects.filter(
                user=user,
                is_deleted=False,
            )
            .select_related("item")
            .prefetch_related("members")
            .order_by("-created_at")[:5]
        )

        event_bookings = (
            EventBooking.objects.filter(
                user=user,
                is_deleted=False,
            )
            .select_related("event")
            .order_by("-created_at")
        )

        exclusive_events = ExclusiveEvent.objects.filter(
            event_date__gte=today,
            is_active=True,
            is_deleted=False,
        ).order_by("event_date", "start_time")[:6]

        combo_packs = ComboPack.objects.filter(
            is_active=True,
            is_deleted=False,
        )

        loyalty_transactions = LoyaltyTransaction.objects.filter(
            user=user,
            is_deleted=False,
        ).order_by("-created_at")[:10]

        spinner_history = (
            SpinnerSpin.objects.filter(
                user=user,
                is_deleted=False,
            )
            .select_related("reward")
            .order_by("-spun_at")[:5]
        )

        today = timezone.localdate()

        current_week = today.isocalendar()[1]
        current_year = today.year

        has_spun_this_week = SpinnerSpin.objects.filter(
            user=user,
            spin_week=current_week,
            spin_year=current_year,
            is_deleted=False,
        ).exists()
        spinner_rewards = SpinnerReward.objects.filter(
            is_active=True,
            is_deleted=False,
        )

        upcoming_booking = (
            Booking.objects.filter(
                user=user,
                is_deleted=False,
                booking_date__gte=today,
                status__in=[
                    Booking.Status.CONFIRMED,
                    Booking.Status.PENDING,
                ],
            )
            .select_related("item")
            .order_by("booking_date", "start_time")
            .first()
        )

        return Response(
            {
                "user_details": UserDetailsSerializer(
                    user,
                    context={"request": request},
                ).data,
                "dashboard_stats": {
                    "total_bookings": Booking.objects.filter(
                        user=user,
                        is_deleted=False,
                    ).count(),
                    "total_events": EventBooking.objects.filter(
                        user=user,
                        is_deleted=False,
                    ).count(),
                    "total_spins": SpinnerSpin.objects.filter(
                        user=user,
                        is_deleted=False,
                    ).count(),
                    "loyalty_points": user.loyalty_points,
                },
                "games_list": GameSerializer(
                    games,
                    many=True,
                    context={"request": request},
                ).data,
                "spinner": {
                    "can_spin": not has_spun_this_week,
                    "spin_history": SpinnerSpinSerializer(
                        spinner_history,
                        many=True,
                    ).data,
                },
                "upcoming_booking": (
                    BookingSerializer(
                        upcoming_booking,
                        context={"request": request},
                    ).data
                    if upcoming_booking
                    else None
                ),
                "loyalty_points": {
                    "current_points": user.loyalty_points,
                    "transactions": LoyaltyTransactionSerializer(
                        loyalty_transactions,
                        many=True,
                    ).data,
                },
                "recent_bookings": BookingSerializer(
                    recent_bookings,
                    many=True,
                    context={"request": request},
                ).data,
                "event_bookings": EventBookingSerializer(
                    event_bookings,
                    many=True,
                    context={"request": request},
                ).data,
                "exclusive_events": ExclusiveEventSerializer(
                    exclusive_events,
                    many=True,
                    context={"request": request},
                ).data,
                "combo_offers": ComboPackSerializer(
                    combo_packs,
                    many=True,
                    context={"request": request},
                ).data,
                "spinner": {
                    "can_spin": not has_spun_this_week,
                    "rewards": UserSpinnerRewardSerializer(
                        spinner_rewards, many=True
                    ).data,
                    "spin_history": SpinnerSpinSerializer(
                        spinner_history,
                        many=True,
                    ).data,
                },
            },
            status=status.HTTP_200_OK,
        )
