"""User-facing exclusive event and event-booking views."""

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import EventBooking, ExclusiveEvent
from gaming.serializers import EventBookingSerializer, UpcomingEventSerializer


class UserUpcomingEventsAPIView(ListAPIView):

    serializer_class = UpcomingEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            ExclusiveEvent.objects
            .filter(
                is_deleted=False,
                is_active=True,
                event_date__gte=timezone.localdate(),
            )
            .order_by("event_date", "start_time")
        )


class UserBookEventAPIView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):

        try:
            event = ExclusiveEvent.objects.select_for_update().get(
                pk=pk,
                is_deleted=False,
                is_active=True
            )
        except ExclusiveEvent.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=404,
            )

        if event.event_date < timezone.localdate():
            return Response(
                {"detail": "Event already finished."},
                status=400,
            )
        if (
            event.event_date == timezone.localdate()
            and event.end_time <= timezone.localtime().time().replace(tzinfo=None)
        ):
            return Response(
                {"detail": "Event has already finished."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if EventBooking.objects.filter(
            event=event,
            user=request.user
        ).exclude(
            status=EventBooking.Status.CANCELLED
        ).exists():

            return Response(
                {"detail": "You have already booked this event."},
                status=400,
            )

        if event.available_slots <= 0:
            return Response(
                {"detail": "Event is full."},
                status=400,
            )

        booking = EventBooking.objects.create(
            event=event,
            user=request.user,
            full_name=request.user.full_name,
            email=request.user.email,
            phone=request.user.phone,
            amount_paid=event.price,
            status=EventBooking.Status.PENDING,
        )

        data = EventBookingSerializer(booking, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED)


class UserEventBookingsAPIView(ListAPIView):

    serializer_class = EventBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            EventBooking.objects
            .filter(user=self.request.user)
            .select_related("event")
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        return {
            "request": self.request,
        }


class UserUpcomingBookingsAPIView(ListAPIView):

    serializer_class = EventBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):

        today = timezone.localdate()

        return (
            EventBooking.objects
            .filter(
                user=self.request.user,
                event__event_date__gte=today,
            )
            .exclude(
                status=EventBooking.Status.CANCELLED
            )
            .select_related("event")
            .order_by("event__event_date")
        )


class UserPreviousBookingsAPIView(ListAPIView):

    serializer_class = EventBookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):

        today = timezone.localdate()

        return (
            EventBooking.objects
            .filter(
                user=self.request.user,
                event__event_date__lt=today,
            )
            .select_related("event")
            .order_by("-event__event_date")
        )


class UserCancelEventBookingAPIView(APIView):

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):

        try:
            booking = EventBooking.objects.select_for_update(of=("self",)).select_related("event").get(
                pk=pk,
                user=request.user,
            )
        except EventBooking.DoesNotExist:
            return Response(
                {"detail": "Booking not found."},
                status=404,
            )

        if booking.status == EventBooking.Status.CANCELLED:
            return Response(
                {"detail": "Already cancelled."},
                status=400,
            )

        if booking.status in (EventBooking.Status.ATTENDED, EventBooking.Status.REJECTED):
            return Response(
                {"detail": f"A {booking.status} booking cannot be cancelled."},
                status=400,
            )

        if booking.event.event_date <= timezone.localdate():
            return Response(
                {"detail": "Cannot cancel after the event date."},
                status=400,
            )

        booking.status = EventBooking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])

        return Response(
            {"detail": "Booking cancelled successfully."}
        )
