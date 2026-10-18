"""User game-booking, wallet, slot and cancellation views."""

from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import Booking, BookingMember, EventBooking, GamingItem
from gaming.serializers import (
    AvailableSlotSerializer,
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingHistorySerializer,
    BookingListSerializer,
    CancelBookingSerializer,
    UserBookingWalletSerializer,
    UserEventBookingWalletSerializer,
)
from gaming.utils.loyalty import reverse_booking_loyalty_points


class UserBookingCreateAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        serializer = BookingCreateSerializer(
            data=request.data, context={"request": request}
        )

        serializer.is_valid(raise_exception=True)

        booking = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Booking created successfully.",
                "booking": BookingDetailSerializer(
                    booking, context={"request": request}
                ).data,
            },
            status=201,
        )


class UserBookingListAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        bookings = (
            Booking.objects.filter(
                user=request.user,
                status__in=[
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ],
            )
            .select_related(
                "item",
                "combo_pack",
            )
            .prefetch_related(
                "members",
            )
            .order_by(
                "booking_date",
                "start_time",
            )
        )

        serializer = BookingListSerializer(
            bookings,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "success": True,
                "count": bookings.count(),
                "results": serializer.data,
            }
        )


class UserBookingDetailAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):

        booking = get_object_or_404(
            Booking.objects.select_related(
                "item",
                "item__category",
                "combo_pack",
                "approved_by",
            ).prefetch_related(
                "members",
            ),
            pk=pk,
            user=request.user,
        )

        serializer = BookingDetailSerializer(
            booking,
            context={"request": request},
        )

        return Response(
            {
                "success": True,
                "data": serializer.data,
            }
        )


class UserBookingHistoryAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        bookings = (
            Booking.objects.filter(
                user=request.user,
                status__in=[
                    Booking.Status.COMPLETED,
                    Booking.Status.CANCELLED,
                ],
            )
            .select_related(
                "item",
                "combo_pack",
            )
            .order_by("-booking_date", "-start_time")
        )

        serializer = BookingHistorySerializer(
            bookings,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "success": True,
                "count": bookings.count(),
                "results": serializer.data,
            }
        )


class UserCancelBookingAPIView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request, pk):

        booking = get_object_or_404(
            Booking.objects.select_for_update(of=("self",)),
            pk=pk,
            user=request.user,
        )

        if booking.status != Booking.Status.PENDING:

            return Response(
                {
                    "success": False,
                    "detail": "Only pending bookings can be cancelled.",
                    "message": "Only pending bookings can be cancelled.",
                },
                status=400,
            )

        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = request.user
        booking.cancelled_from = "user"
        booking.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancelled_from", "updated_at"])
        reverse_booking_loyalty_points(booking)

        return Response(
            {
                "success": True,
                "message": "Booking cancelled successfully.",
            }
        )


class UserAvailableSlotsAPIView(APIView):

    permission_classes = [IsAuthenticated]

    SLOT_DURATION = 60  # minutes

    def get(self, request, pk):

        date = request.GET.get("date")

        if not date:
            return Response(
                {"success": False, "message": "Date is required."},
                status=400,
            )

        try:
            booking_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"success": False, "message": "Date must use YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item = get_object_or_404(
            GamingItem,
            pk=pk,
            is_active=True,
            is_deleted=False,
            maintenance_mode=False,
        )

        bookings = Booking.objects.filter(
            item=item,
            booking_date=booking_date,
            is_deleted=False,
        ).exclude(status=Booking.Status.CANCELLED)

        opening = time(9, 0)
        closing = time(23, 0)

        slots = []

        current = datetime.combine(
            booking_date,
            opening,
        )

        end = datetime.combine(
            booking_date,
            closing,
        )

        now = timezone.localtime()

        while current < end:

            slot_end = current + timedelta(minutes=self.SLOT_DURATION)

            available = (
                booking_date > now.date()
                or current.time() > now.time().replace(tzinfo=None)
            )

            for booking in bookings:

                booking_start = datetime.combine(
                    booking_date,
                    booking.start_time,
                )

                booking_end = datetime.combine(
                    booking_date,
                    booking.end_time,
                )

                if current < booking_end and slot_end > booking_start:
                    available = False
                    break

            slots.append(
                {
                    "start_time": current.time(),
                    "end_time": slot_end.time(),
                    "available": available,
                }
            )

            current = slot_end

        serializer = AvailableSlotSerializer(
            slots,
            many=True,
        )

        return Response(
            {
                "success": True,
                "results": serializer.data,
            }
        )


class UserBookingWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate()

        bookings = (
            Booking.objects.filter(user=request.user, is_deleted=False)
            .select_related("item", "item__category", "combo_pack")
            .prefetch_related(Prefetch("members", queryset=BookingMember.objects.all()))
        )
        event_bookings = (
            EventBooking.objects.filter(user=request.user, is_deleted=False)
            .select_related("event")
            .prefetch_related("members")
        )

        active_statuses = [
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ]
        active_event_statuses = [
            EventBooking.Status.PENDING,
            EventBooking.Status.APPROVED,
        ]

        upcoming_bookings = [
            booking
            for booking in bookings.filter(status__in=active_statuses)
            if timezone.make_aware(
                timezone.datetime.combine(booking.booking_date, booking.end_time)
            )
            >= now
        ]
        upcoming_events = [
            event_booking
            for event_booking in event_bookings.filter(status__in=active_event_statuses)
            if timezone.make_aware(
                timezone.datetime.combine(
                    event_booking.event.event_date, event_booking.event.end_time
                )
            )
            >= now
        ]

        history_bookings = [
            booking
            for booking in bookings.exclude(
                id__in=[item.id for item in upcoming_bookings]
            )
            if booking.booking_date <= today
            or booking.status in [Booking.Status.COMPLETED, Booking.Status.CANCELLED]
        ]
        history_events = [
            event_booking
            for event_booking in event_bookings.exclude(
                id__in=[item.id for item in upcoming_events]
            )
            if event_booking.event.event_date <= today
            or event_booking.status
            in [
                EventBooking.Status.ATTENDED,
                EventBooking.Status.CANCELLED,
                EventBooking.Status.REJECTED,
            ]
        ]

        upcoming = self._serialize_booking_group(
            request, upcoming_bookings, upcoming_events
        )
        history = self._serialize_booking_group(
            request, history_bookings, history_events
        )

        return Response(
            {
                "upcoming": sorted(upcoming, key=lambda item: item["starts_at"]),
                "history": sorted(
                    history, key=lambda item: item["starts_at"], reverse=True
                ),
                "counts": {
                    "upcoming": len(upcoming),
                    "history": len(history),
                    "combo": bookings.filter(combo_pack__isnull=False).count(),
                    "event": event_bookings.count(),
                },
            }
        )

    def _serialize_booking_group(self, request, bookings, event_bookings):
        context = {"request": request}
        booking_data = UserBookingWalletSerializer(
            bookings, many=True, context=context
        ).data
        event_data = UserEventBookingWalletSerializer(
            event_bookings, many=True, context=context
        ).data
        return [*booking_data, *event_data]


class UserCancelBookingView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, booking_id):
        serializer = CancelBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        booking = (
            Booking.objects.select_for_update(of=("self",))
            .filter(booking_id=booking_id, user=request.user, is_deleted=False)
            .select_related("item", "combo_pack")
            .first()
        )
        if booking:
            return self._cancel_regular_booking(request, booking, serializer)

        event_booking = (
            EventBooking.objects.filter(
                booking_id=booking_id, user=request.user, is_deleted=False
            )
            .select_related("event")
            .first()
        )
        if event_booking:
            return self._cancel_event_booking(request, event_booking)

        return Response(
            {"detail": "Booking not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def _cancel_regular_booking(self, request, booking, serializer):
        if booking.status in [Booking.Status.CANCELLED, Booking.Status.COMPLETED]:
            return Response(
                {"detail": "This booking cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking_start = timezone.make_aware(
            timezone.datetime.combine(booking.booking_date, booking.start_time)
        )
        if timezone.now() >= booking_start:
            return Response(
                {"detail": "Bookings cannot be cancelled after they start."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = request.user
        booking.cancelled_from = "user"
        booking.cancellation_reason = serializer.validated_data.get("reason", "")
        if booking.payment_status == Booking.PaymentStatus.PAID:
            booking.refund_status = "pending"
            booking.refund_amount = booking.price_paid
        booking.save()
        reverse_booking_loyalty_points(booking)

        return Response(
            UserBookingWalletSerializer(booking, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def _cancel_event_booking(self, request, event_booking):
        if event_booking.status in [
            EventBooking.Status.CANCELLED,
            EventBooking.Status.ATTENDED,
            EventBooking.Status.REJECTED,
        ]:
            return Response(
                {"detail": "This event booking cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_start = timezone.make_aware(
            timezone.datetime.combine(
                event_booking.event.event_date, event_booking.event.start_time
            )
        )
        if timezone.now() >= event_start:
            return Response(
                {"detail": "Event bookings cannot be cancelled after they start."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_booking.status = EventBooking.Status.CANCELLED
        event_booking.save(update_fields=["status", "updated_at"])

        return Response(
            UserEventBookingWalletSerializer(
                event_booking, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )


class AvailableGamingSlotsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    OPEN_TIME = time(10, 0)
    CLOSE_TIME = time(22, 0)

    def get(self, request, item_id):

        date = request.query_params.get("date")

        if not date:
            return Response(
                {"detail": "date is required"},
                status=400
            )

        try:
            booking_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "date must use YYYY-MM-DD format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item = get_object_or_404(
                GamingItem,
                pk=item_id,
                is_active=True,
                is_deleted=False,
                maintenance_mode=False,
            )

        bookings = Booking.objects.filter(
            item=item,
            booking_date=booking_date,
            is_deleted=False,
        ).exclude(
            status=Booking.Status.CANCELLED
        )

        current = datetime.combine(
            booking_date,
            self.OPEN_TIME
        )

        end = datetime.combine(
            booking_date,
            self.CLOSE_TIME
        )

        slots = []
        now = timezone.localtime()

        while current < end:

            slot_end = current + timedelta(hours=1)

            is_in_future = (
                booking_date > now.date()
                or current.time() > now.time().replace(tzinfo=None)
            )
            booked = not is_in_future or bookings.filter(
                start_time__lt=slot_end.time(),
                end_time__gt=current.time()
            ).exists()

            slots.append({

                "start_time": current.time(),

                "end_time": slot_end.time(),

                "available": not booked

            })

            current += timedelta(hours=1)

        serializer = AvailableSlotSerializer(slots, many=True)
        return Response(serializer.data)
