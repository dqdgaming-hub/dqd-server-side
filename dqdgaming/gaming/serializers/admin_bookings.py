"""Admin game/combo booking serializers."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from gaming.models import Booking, BookingMember
from gaming.serializers.common import clean_phone_field
from gaming.utils.image_encryption import safe_image_to_data_uri
from gaming.utils.whatsapp import booking_whatsapp_url


class BookingMemberSerializer(serializers.ModelSerializer):

    class Meta:
        model = BookingMember
        fields = [
            "id",
            "name",
            "phone",
            "is_admin_added",
        ]
        read_only_fields = ["id", "is_admin_added"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Member name is required.")
        return value

    def validate_phone(self, value):
        return clean_phone_field(value) or ""


class AdminBookingCreateSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(
        many=True,
        required=False,
        write_only=True,
    )

    class Meta:
        model = Booking
        fields = [
            "user",
            "guest_name",
            "guest_email",
            "guest_phone",
            "item",
            "combo_pack",
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
            "is_happy_hour",
            "use_manual_loyalty_points",
            "manual_loyalty_points",
            "members",
        ]

    # ── cross-field validation ──────────────────────────────

    def validate_guest_phone(self, value):
        return clean_phone_field(value)

    def validate(self, attrs):
        user = attrs.get("user")
        guest_name = (attrs.get("guest_name") or "").strip()
        guest_email = (attrs.get("guest_email") or "").strip()
        guest_phone = attrs.get("guest_phone") or ""

        if not attrs.get("item") and not attrs.get("combo_pack"):
            raise serializers.ValidationError({"item": "Choose a game or a combo pack."})

        # Guest bookings need a name and a way to reach them
        if not user:
            errors = {}
            if not guest_name:
                errors["guest_name"] = "Guest name is required."
            if not guest_phone and not guest_email:
                errors["guest_phone"] = "Guest mobile number is required."
            if errors:
                raise serializers.ValidationError(errors)
            attrs["guest_name"] = guest_name
            attrs["guest_email"] = guest_email or None
        elif not user.is_active or user.is_deleted:
            raise serializers.ValidationError({"user": "This customer account is deactivated."})

        for money_field in ("subtotal", "discount_amount", "total_amount", "price_paid"):
            value = attrs.get(money_field)
            if value is not None and value < 0:
                raise serializers.ValidationError({money_field: "Amount cannot be negative."})

        # Time sanity (model.clean() also enforces this, but catch it here
        # to return a serializer-level 400 rather than a 500)
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )

        item = attrs.get("item")
        booking_date = attrs.get("booking_date")
        if item and booking_date and start_time and end_time:
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
                    {"start_time": "This slot is already booked."}
                )

        # If manual loyalty override is toggled, the points value must be present
        if (
            attrs.get("use_manual_loyalty_points")
            and attrs.get("manual_loyalty_points") is None
        ):
            raise serializers.ValidationError(
                {
                    "manual_loyalty_points": "Required when use_manual_loyalty_points is True."
                }
            )

        return attrs

    # ── create ─────────────────────────────────────────────

    def create(self, validated_data):
        members_data = validated_data.pop("members", [])

        combo_pack = validated_data.get("combo_pack")

        validated_data["created_by_admin"] = True

        # Admin manually entered loyalty points
        if validated_data.get("use_manual_loyalty_points"):
            validated_data["loyalty_points_earned"] = (
                validated_data.get("manual_loyalty_points") or 0
            )

        # Combo pack gives loyalty points
        elif combo_pack:
            validated_data["loyalty_points_earned"] = combo_pack.loyalty_bonus or 0

        try:
            booking = Booking.objects.create(**validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        BookingMember.objects.bulk_create(
            [
                BookingMember(booking=booking, is_admin_added=True, **member)
                for member in members_data
            ]
        )

        return booking


class AdminBookingListSerializer(serializers.ModelSerializer):

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()
    booking_type = serializers.ReadOnlyField()

    item_name = serializers.CharField(source="item.name", read_only=True)
    combo_name = serializers.SerializerMethodField()

    awarded_loyalty_points = serializers.ReadOnlyField()
    whatsapp_url = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "customer_name",
            "customer_email",
            "customer_phone",
            "whatsapp_url",
            "booking_type",
            "item_name",
            "combo_name",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "price_paid",
            "is_happy_hour",
            "checked_in",
            "awarded_loyalty_points",
            "created_at",
        ]

    def get_combo_name(self, obj):
        return obj.combo_pack.name if obj.combo_pack else None

    def get_whatsapp_url(self, obj):
        # Resend the confirmation from the list (confirmed bookings only).
        return booking_whatsapp_url(obj) if obj.status == Booking.Status.CONFIRMED else None


class AdminBookingDetailSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, read_only=True)

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()
    booking_type = serializers.ReadOnlyField()

    awarded_loyalty_points = serializers.SerializerMethodField()

    # Nested item / combo summaries (avoid exposing full nested objects)
    item = serializers.SerializerMethodField()
    combo_pack = serializers.SerializerMethodField()

    # QR code as absolute URL
    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            # customer
            "user",
            "customer_name",
            "customer_email",
            "customer_phone",
            "created_by_admin",
            # item
            "item",
            "combo_pack",
            "booking_type",
            # slot
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            # payment
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "payment_status",
            # loyalty
            "loyalty_points_earned",
            "use_manual_loyalty_points",
            "manual_loyalty_points",
            "awarded_loyalty_points",
            # status
            "status",
            "approved_by",
            "approved_at",
            # happy hour
            "is_happy_hour",
            # QR / check-in
            "qr_token",
            "qr_code",
            "qr_sent",
            "checked_in",
            "checked_in_at",
            # misc
            "notes",
            "members",
            "created_at",
            "updated_at",
        ]

    def get_awarded_loyalty_points(self, obj):
        return obj.awarded_loyalty_points

    def get_item(self, obj):
        if not obj.item:
            return None
        return {
            "id": str(obj.item.id),
            "name": obj.item.name,
            "price_per_hour": str(obj.item.price_per_hour),
        }

    def get_combo_pack(self, obj):
        if not obj.combo_pack:
            return None
        return {
            "id": str(obj.combo_pack.id),
            "name": obj.combo_pack.name,
            "combo_price": str(obj.combo_pack.combo_price),
        }

    def get_qr_code(self, obj):
        if not obj.qr_code:
            return None
        request = self.context.get("request")
        if request:
            return safe_image_to_data_uri(obj.qr_code)
        return safe_image_to_data_uri(obj.qr_code)
