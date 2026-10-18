"""Admin happy-hour and spinner-reward views."""

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import (
    GamingItem,
    HappyHourAllocation,
    HappyHourBooking,
    HappyHourSlot,
    HappyHourTemplateSlot,
    SpinnerReward,
    SpinnerSpin,
)
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminAssignHappyHourGameSerializer,
    HappyHourAllocationSerializer,
    HappyHourBookingSerializer,
    HappyHourTemplateSlotSerializer,
    SpinnerRewardSerializer,
)


class AdminHappyHourTemplateListCreateView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        slots = HappyHourTemplateSlot.objects.all()

        return Response(
            HappyHourTemplateSlotSerializer(
                slots,
                many=True,
            ).data
        )

    def post(self, request):

        serializer = HappyHourTemplateSlotSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(
            serializer.data,
            status=201,
        )


class AdminSpinnerRewardListCreateView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        rewards = SpinnerReward.objects.select_related("template_slot")

        return Response(
            SpinnerRewardSerializer(
                rewards,
                many=True,
            ).data
        )

    def post(self, request):

        serializer = SpinnerRewardSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(
            serializer.data,
            status=201,
        )


class AdminHappyHourBookingsView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        bookings = HappyHourBooking.objects.select_related(
            "happy_hour_slot",
            "booking",
        ).order_by("-created_at")

        return Response(
            HappyHourBookingSerializer(
                bookings,
                many=True,
            ).data
        )


class AdminSpinnerSpinsView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        spins = SpinnerSpin.objects.select_related(
            "user",
            "reward",
        ).order_by("-spun_at")

        data = []

        for spin in spins:
            data.append(
                {
                    "id": spin.id,
                    "user": spin.user.full_name,
                    "reward": spin.reward.reward_name,
                    "week": spin.spin_week,
                    "year": spin.spin_year,
                    "spun_at": spin.spun_at,
                }
            )

        return Response(data)


class AdminAssignHappyHourGameView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def post(self, request, pk):

        slot = get_object_or_404(
            HappyHourSlot,
            pk=pk,
        )

        serializer = AdminAssignHappyHourGameSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        game = get_object_or_404(
            GamingItem, pk=serializer.validated_data["gaming_item"]
        )

        slot.gaming_item = game
        slot.save(update_fields=["gaming_item"])

        return Response({"success": True, "message": "Game assigned successfully."})


class AdminVerifyHappyHourView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request):

        slot_id = str(request.data.get("slot_id") or "").strip()
        try:
            uuid.UUID(slot_id)
        except (ValueError, AttributeError, TypeError):
            return Response({"valid": False, "message": "Invalid slot."}, status=400)

        slot = get_object_or_404(
            HappyHourSlot.objects.select_for_update(of=("self",)).select_related("user", "template_slot"),
            pk=slot_id,
        )

        if slot.is_used:

            return Response(
                {
                    "valid": False,
                    "message": "Already redeemed",
                }
            )

        slot.is_used = True
        slot.redeemed_at = timezone.now()

        slot.save()

        return Response(
            {
                "valid": True,
                "user": slot.user.full_name,
                "slot": slot.template_slot.slot_name,
            }
        )


class AdminHappyHourAllocationViewSet(viewsets.ModelViewSet):

    queryset = HappyHourAllocation.objects.all()
    serializer_class = HappyHourAllocationSerializer

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get_queryset(self):
        queryset = HappyHourAllocation.objects.all()

        date = self.request.query_params.get("date")
        is_active = self.request.query_params.get("is_active")

        if date:
            queryset = queryset.filter(date=date)

        if is_active is not None:
            queryset = queryset.filter(
                is_active=is_active.lower() == "true"
            )

        return queryset.order_by("date", "start_time")
