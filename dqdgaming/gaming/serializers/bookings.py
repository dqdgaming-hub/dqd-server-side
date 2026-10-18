"""User game-booking, wallet and cancellation serializers."""

from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from gaming.models import AppSetting, Booking, BookingMember, EventBooking
from gaming.serializers.admin_bookings import BookingMemberSerializer
from gaming.serializers.games import UserGamingItemDetailSerializer
from gaming.utils.image_encryption import safe_image_to_data_uri


class BookingCreateSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, required=False)

    class Meta:
        model = Booking
        fields = [
            "item",
            "booking_date",
            "start_time",
            "end_time",
            "members",
            "notes",
        ]

    def validate(self, attrs):

        item = attrs["item"]

        booking_date = attrs["booking_date"]
        start_time = attrs["start_time"]
        end_time = attrs["end_time"]

        members = attrs.get("members", [])

        if item.maintenance_mode:
            raise serializers.ValidationError(
                "This game is currently under maintenance."
            )

        today = timezone.localdate()
        if booking_date < today:
            raise serializers.ValidationError(
                {"booking_date": "Booking date cannot be in the past."}
            )
        if (
            booking_date == today
            and start_time <= timezone.localtime().time().replace(tzinfo=None)
        ):
            raise serializers.ValidationError(
                {"start_time": "Booking start time must be in the future."}
            )

        if start_time >= end_time:
            raise serializers.ValidationError("End time must be after start time.")

        # One booking per item per slot (the item row is also locked on save).
        overlapping = Booking.objects.filter(
            item=item,
            booking_date=booking_date,
            start_time__lt=end_time,
            end_time__gt=start_time,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
            ],
        )
        if overlapping.exists():
            raise serializers.ValidationError(
                {"message": "This slot is already booked. Please pick another time."}
            )

        if (datetime.combine(booking_date, end_time) - datetime.combine(booking_date, start_time)).total_seconds() > 12 * 3600:
            raise serializers.ValidationError({"end_time": "A booking can be at most 12 hours long."})

        total_people = len(members) + 1

        if total_people < item.min_capacity:
            raise serializers.ValidationError(
                f"This game requires at least {item.min_capacity} player(s)."
            )

        if total_people > item.max_capacity:
            raise serializers.ValidationError(
                f"Maximum {item.max_capacity} players allowed."
            )

        start = datetime.combine(booking_date, start_time)
        end = datetime.combine(booking_date, end_time)

        hours = Decimal(str((end - start).total_seconds() / 3600))

        attrs["total_hours"] = hours
        attrs["subtotal"] = hours * item.price_per_hour
        attrs["discount_amount"] = 0
        attrs["total_amount"] = attrs["subtotal"]

        return attrs

    @transaction.atomic
    def create(self, validated_data):

        members = validated_data.pop("members", [])

        settings_row = AppSetting.objects.filter(is_active=True).order_by("-created_at").first()
        points = settings_row.booking_loyalty_points if settings_row else 10

        try:
            booking = Booking.objects.create(
                user=self.context["request"].user,
                total_hours=validated_data.pop("total_hours"),
                subtotal=validated_data.pop("subtotal"),
                discount_amount=validated_data.pop("discount_amount"),
                total_amount=validated_data.pop("total_amount"),
                # Credited when an admin confirms the booking, so points
                # cannot be farmed by booking and cancelling.
                loyalty_points_earned=points,
                **validated_data,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"message": exc.messages[0]}) from exc

        BookingMember.objects.bulk_create(
            [
                BookingMember(
                    booking=booking,
                    name=member["name"],
                    phone=member.get("phone", ""),
                )
                for member in members
            ]
        )

        return booking


class BookingListSerializer(serializers.ModelSerializer):

    game_name = serializers.SerializerMethodField()
    game_image = serializers.SerializerMethodField()
    total_people = serializers.ReadOnlyField()
    can_check_in = serializers.ReadOnlyField()
    is_qr_valid = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "game_name",
            "game_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "total_people",
            "can_check_in",
            "is_qr_valid",
        ]

    def get_game_name(self, obj):

        if obj.item:
            return obj.item.name

        if obj.combo_pack:
            return obj.combo_pack.name

        return None

    def get_game_image(self, obj):

        request = self.context.get("request")

        image = None

        if obj.item:
            image = obj.item.image

        elif obj.combo_pack:
            image = obj.combo_pack.image

        if image:
            return safe_image_to_data_uri(image)

        return None


class BookingDetailSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, read_only=True)

    game = UserGamingItemDetailSerializer(source="item", read_only=True)

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()

    total_people = serializers.ReadOnlyField()

    booking_type = serializers.ReadOnlyField()

    awarded_loyalty_points = serializers.ReadOnlyField()

    can_check_in = serializers.ReadOnlyField()

    is_qr_valid = serializers.ReadOnlyField()

    approved_by_name = serializers.SerializerMethodField()

    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = Booking

        fields = [
            "id",
            "booking_id",
            "booking_type",
            "game",
            "customer_name",
            "customer_email",
            "customer_phone",
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "status",
            "payment_status",
            "notes",
            "members",
            "total_people",
            "loyalty_points_earned",
            "awarded_loyalty_points",
            "approved_by_name",
            "approved_at",
            "qr_token",
            "qr_code",
            "checked_in",
            "checked_in_at",
            "can_check_in",
            "is_qr_valid",
            "created_at",
        ]

    def get_approved_by_name(self, obj):

        if obj.approved_by:
            return obj.approved_by.full_name

        return None

    def get_qr_code(self, obj):

        request = self.context.get("request")

        if obj.qr_code:
            return safe_image_to_data_uri(obj.qr_code)

        return None


class BookingHistorySerializer(serializers.ModelSerializer):

    game_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking

        fields = [
            "id",
            "booking_id",
            "game_name",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "loyalty_points_earned",
            "created_at",
        ]

    def get_game_name(self, obj):

        if obj.item:
            return obj.item.name

        if obj.combo_pack:
            return obj.combo_pack.name

        return None


class AvailableSlotSerializer(serializers.Serializer):
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    available = serializers.BooleanField()


class UserBookingMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = ["id", "name", "phone", "is_admin_added"]


class UserBookingWalletSerializer(serializers.ModelSerializer):
    booking_kind = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    members = UserBookingMemberSerializer(many=True, read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    qr_token = serializers.UUIDField(read_only=True)
    is_qr_valid = serializers.BooleanField(read_only=True)
    can_cancel = serializers.SerializerMethodField()
    starts_at = serializers.SerializerMethodField()
    ends_at = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "booking_kind",
            "title",
            "image",
            "category",
            "booking_date",
            "start_time",
            "end_time",
            "starts_at",
            "ends_at",
            "total_hours",
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "payment_status",
            "status",
            "loyalty_points_earned",
            "total_people",
            "members",
            "qr_code_url",
            "qr_token",
            "qr_sent",
            "is_qr_valid",
            "checked_in",
            "checked_in_at",
            "can_cancel",
            "cancelled_at",
            "cancellation_reason",
            "refund_amount",
            "refund_status",
            "notes",
            "created_at",
        ]

    def get_booking_kind(self, obj):
        return "combo" if obj.combo_pack_id else "booking"

    def get_title(self, obj):
        if obj.combo_pack:
            return obj.combo_pack.name
        if obj.item:
            return obj.item.name
        return "Booking"

    def get_image(self, obj):
        image = None
        if obj.combo_pack and obj.combo_pack.image:
            image = obj.combo_pack.image
        elif obj.item and obj.item.image:
            image = obj.item.image
        return self._absolute_media_url(image)

    def get_category(self, obj):
        if obj.item and obj.item.category:
            return obj.item.category.name
        if obj.combo_pack:
            return "Combo"
        return ""

    def get_qr_code_url(self, obj):
        return self._absolute_media_url(obj.qr_code)

    def get_can_cancel(self, obj):
        if obj.status in [Booking.Status.CANCELLED, Booking.Status.COMPLETED]:
            return False
        booking_start = timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.start_time)
        )
        return timezone.now() < booking_start

    def get_starts_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.start_time)
        ).isoformat()

    def get_ends_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.end_time)
        ).isoformat()

    def _absolute_media_url(self, file_field):
        return safe_image_to_data_uri(file_field)


class UserEventBookingWalletSerializer(serializers.ModelSerializer):
    booking_kind = serializers.SerializerMethodField()
    title = serializers.CharField(source="event.title", read_only=True)
    image = serializers.SerializerMethodField()
    booking_date = serializers.DateField(source="event.event_date", read_only=True)
    start_time = serializers.TimeField(source="event.start_time", read_only=True)
    end_time = serializers.TimeField(source="event.end_time", read_only=True)
    starts_at = serializers.SerializerMethodField()
    ends_at = serializers.SerializerMethodField()
    total_amount = serializers.DecimalField(
        source="event.price", max_digits=10, decimal_places=2, read_only=True
    )
    price_paid = serializers.DecimalField(
        source="amount_paid", max_digits=10, decimal_places=2, read_only=True
    )
    payment_status = serializers.SerializerMethodField()
    qr_code_url = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    total_people = serializers.SerializerMethodField()

    class Meta:
        model = EventBooking
        fields = [
            "id",
            "booking_id",
            "booking_kind",
            "title",
            "image",
            "booking_date",
            "start_time",
            "end_time",
            "starts_at",
            "ends_at",
            "total_amount",
            "price_paid",
            "payment_status",
            "status",
            "total_people",
            "members",
            "qr_code_url",
            "qr_token",
            "qr_sent",
            "checked_in",
            "checked_in_at",
            "can_cancel",
            "notes",
            "created_at",
        ]

    def get_booking_kind(self, obj):
        return "event"

    def get_image(self, obj):
        return safe_image_to_data_uri(obj.event.image)

    def get_starts_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.start_time)
        ).isoformat()

    def get_ends_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.end_time)
        ).isoformat()

    def get_payment_status(self, obj):
        return "paid" if obj.amount_paid and obj.amount_paid > 0 else "pending"

    def get_qr_code_url(self, obj):
        return safe_image_to_data_uri(obj.qr_code)

    def get_can_cancel(self, obj):
        if obj.status in [EventBooking.Status.CANCELLED, EventBooking.Status.ATTENDED]:
            return False
        event_start = timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.start_time)
        )
        return timezone.now() < event_start

    def get_members(self, obj):
        return [{"id": str(m.id), "name": m.name, "phone": m.phone} for m in obj.members.all()]

    def get_total_people(self, obj):
        return len(obj.members.all()) + 1


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
