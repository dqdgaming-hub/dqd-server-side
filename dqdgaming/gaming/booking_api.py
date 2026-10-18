"""Unified booking API — the same three calls for every kind of booking.

GET  /api/auth/user/book/options/?kind=game&id=<uuid>
GET  /api/auth/user/book/slots/?kind=game&id=<uuid>&date=YYYY-MM-DD
POST /api/auth/user/book/   {kind, id, date, start_time, hours, members[], notes}

kind is one of: game, combo, event, loyalty (pay with points).
"""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from gaming.services import booking as booking_service
from gaming.services.booking import BookingError


class _TargetQuery(serializers.Serializer):
    kind = serializers.ChoiceField(choices=booking_service.KINDS)
    id = serializers.UUIDField()


class _SlotsQuery(_TargetQuery):
    date = serializers.DateField()


class _MemberInput(serializers.Serializer):
    name = serializers.CharField(max_length=150, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class BookingRequestSerializer(_TargetQuery):
    date = serializers.DateField(required=False)
    start_time = serializers.TimeField(required=False)
    hours = serializers.IntegerField(required=False, min_value=1, max_value=24, default=1)
    members = _MemberInput(many=True, required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

    def validate(self, attrs):
        if attrs["kind"] != booking_service.EVENT:
            if not attrs.get("date"):
                raise serializers.ValidationError({"date": "Choose a date."})
            if not attrs.get("start_time"):
                raise serializers.ValidationError({"start_time": "Choose a start time."})
        return attrs


def _error(exc):
    return Response(
        {"detail": exc.message, exc.field: [exc.message]},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _target(params):
    return booking_service.get_target(params["kind"], params["id"])


class BookingOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = _TargetQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            target = _target(query.validated_data)
        except BookingError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)
        return Response(booking_service.options(query.validated_data["kind"], target, request.user))


class BookingSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = _SlotsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            target = _target(query.validated_data)
        except BookingError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "date": query.validated_data["date"].isoformat(),
                "slots": booking_service.slots(
                    query.validated_data["kind"], target, query.validated_data["date"]
                ),
            }
        )


class CreateBookingView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = "booking"

    def post(self, request):
        payload = BookingRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        kind = data["kind"]
        try:
            target = _target(data)
            booking = booking_service.create(
                request.user,
                kind,
                target,
                booking_date=data.get("date"),
                start_time=data.get("start_time"),
                hours=data.get("hours", 1),
                members=data.get("members") or [],
                notes=data.get("notes", ""),
            )
        except BookingError as exc:
            return _error(exc)

        return Response(
            {
                "success": True,
                "message": "Booking received. We'll confirm it shortly.",
                "booking": booking_service.summary(kind, booking),
            },
            status=status.HTTP_201_CREATED,
        )
