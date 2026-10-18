"""Spinner, loyalty and happy-hour views for signed-in users."""

import random

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.middleware import DeviceActivityMixin
from gaming.models import (
    HappyHourAllocation,
    LoyaltyTransaction,
    SpinnerReward,
    SpinnerSpin,
)
from gaming.serializers import (
    LoyaltyRedeemedBookingSerializer,
    LoyaltySlotRedemptionSerializer,
    SpinnerRewardSerializer,
    UserHappyHourAllocationSerializer,
)


class UserSpinView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        current_week = today.isocalendar()[1]
        current_year = today.year

        # Guard: one spin per week
        if SpinnerSpin.objects.filter(
            user=user,
            spin_week=current_week,
            spin_year=current_year,
            is_deleted=False,
        ).exists():
            return Response(
                {"detail": "You have already used your spin this week."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Weighted random reward selection
        rewards = SpinnerReward.objects.filter(is_active=True, is_deleted=False)
        if not rewards.exists():
            return Response(
                {"detail": "No rewards configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        population = list(rewards)
        weights = [r.probability for r in population]
        if not any(weights):
            return Response(
                {"detail": "No rewards configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        reward = random.choices(population, weights=weights, k=1)[0]

        # Save spin — unique_together is a safety net against race conditions
        try:
            spin = SpinnerSpin.objects.create(user=user, reward=reward)
        except IntegrityError:
            return Response(
                {"detail": "You have already used your spin this week."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Award loyalty points if it's a points reward
        if (
            reward.reward_type == SpinnerReward.RewardType.POINTS
            and reward.reward_points > 0
        ):
            user.loyalty_points += reward.reward_points
            user.save(update_fields=["loyalty_points"])
            LoyaltyTransaction.objects.create(
                user=user,
                points=reward.reward_points,
                transaction_type=LoyaltyTransaction.TransactionType.SPINNER,
                description=f"Spinner win: {reward.reward_name}",
            )

        return Response(
            {
                "reward": SpinnerRewardSerializer(reward).data,
                "spin_id": spin.id,
            },
            status=status.HTTP_200_OK,
        )


class RedeemLoyaltySlotAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LoyaltySlotRedemptionSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()

        return Response(
            {
                "message": "Loyalty points redeemed. Your game slot is booked!",
                "booking": LoyaltyRedeemedBookingSerializer(booking).data,
            },
            status=status.HTTP_201_CREATED,
        )


class UserLoyaltyAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "loyalty_points": request.user.loyalty_points,
            "redeemable_hours": request.user.loyalty_points // 100
        })


class UserHappyHourAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        today = timezone.localdate()
        current_time = timezone.localtime().time()

        # Get active future/current Happy Hour allocations
        allocations = HappyHourAllocation.objects.filter(
            is_active=True,
            date__gte=today,
        ).order_by(
            "date",
            "start_time",
        )

        upcoming = []

        for allocation in allocations:

            # Future date
            if allocation.date > today:
                upcoming.append(allocation)

            # Today
            elif allocation.date == today:

                # Keep current or upcoming slots
                if allocation.end_time > current_time:
                    upcoming.append(allocation)

        # Only return the nearest Happy Hour
        if not upcoming:
            return Response(
                {
                    "happy_hour": None
                },
                status=status.HTTP_200_OK,
            )

        happy_hour = upcoming[0]

        serializer = UserHappyHourAllocationSerializer(
            happy_hour
        )

        return Response(
            {
                "happy_hour": serializer.data
            },
            status=status.HTTP_200_OK,
        )
