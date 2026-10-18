"""User-facing combo pack and combo-booking views."""

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import Booking, ComboPack
from gaming.serializers import (
    CreateComboBookingSerializer,
    UserComboBookingSerializer,
    UserComboPackDetailSerializer,
    UserComboPackSerializer,
)
from gaming.utils.loyalty import reverse_booking_loyalty_points


def combo_queryset():
    queryset = ComboPack.objects.filter(is_deleted=False, is_active=True)
    for relation in ("gaming_items", "items"):
        try:
            queryset = queryset.prefetch_related(relation)
            break
        except Exception:
            pass
    return queryset


def booking_queryset(user):
    return (
        Booking.objects.filter(user=user, combo_pack__isnull=False)
        .select_related("combo_pack", "user")
        .prefetch_related("members")
    )


class UserComboPackListAPIView(ListAPIView):
    serializer_class = UserComboPackSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return combo_queryset().order_by("name")

    def get_serializer_context(self):
        return {"request": self.request}


class UserComboPackDetailAPIView(RetrieveAPIView):
    serializer_class = UserComboPackDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "id"

    def get_queryset(self):
        return combo_queryset()

    def get_serializer_context(self):
        return {"request": self.request}


class CreateComboBookingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateComboBookingSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        booking = booking_queryset(request.user).get(pk=booking.pk)
        data = UserComboBookingSerializer(booking, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED)


class UserComboBookingsAPIView(ListAPIView):
    serializer_class = UserComboBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return booking_queryset(self.request.user).order_by("-created_at")

    def get_serializer_context(self):
        return {"request": self.request}


class UpcomingComboBookingsAPIView(ListAPIView):
    serializer_class = UserComboBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            booking_queryset(self.request.user)
            .filter(booking_date__gte=timezone.localdate())
            .exclude(status=Booking.Status.CANCELLED)
            .order_by("booking_date", "start_time")
        )

    def get_serializer_context(self):
        return {"request": self.request}


class PreviousComboBookingsAPIView(ListAPIView):
    serializer_class = UserComboBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            booking_queryset(self.request.user)
            .filter(booking_date__lt=timezone.localdate())
            .order_by("-booking_date", "-start_time")
        )

    def get_serializer_context(self):
        return {"request": self.request}


class CancelComboBookingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, id):
        try:
            booking = booking_queryset(request.user).select_for_update(of=("self",)).get(id=id)
        except Booking.DoesNotExist:
            return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

        completed_status = getattr(getattr(Booking, "Status", object), "COMPLETED", "COMPLETED")
        if booking.status == completed_status:
            return Response({"detail": "Completed booking cannot be cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        if booking.status == Booking.Status.CANCELLED:
            return Response({"detail": "Booking is already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        if booking.booking_date <= timezone.localdate():
            return Response({"detail": "Cannot cancel on or after booking date."}, status=status.HTTP_400_BAD_REQUEST)

        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = request.user
        booking.cancelled_from = "user"
        booking.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancelled_from", "updated_at"])

        # Only undo points that were really credited (on admin confirmation).
        reverse_booking_loyalty_points(booking)

        return Response(
            {
                "message": "Booking cancelled successfully.",
                "booking": UserComboBookingSerializer(booking, context={"request": request}).data,
            }
        )
