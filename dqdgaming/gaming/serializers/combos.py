"""User-facing combo pack serializers."""

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from gaming.models import Booking, BookingMember, ComboPack
from gaming.serializers.common import (
    absolute_media_url,
    clean_phone_field,
    combo_max_people,
    combo_price,
)


class ComboGamingItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, required=False)
    image = serializers.SerializerMethodField()

    def get_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "image", None))


class BookingComboMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = ["id", "name", "phone"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Member name is required.")
        return value

    def validate_phone(self, value):
        return clean_phone_field(value) or ""


class UserComboPackSerializer(serializers.ModelSerializer):
    description = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    combo_price = serializers.SerializerMethodField()
    snack_name = serializers.SerializerMethodField()
    snack_price = serializers.SerializerMethodField()
    loyalty_bonus = serializers.SerializerMethodField()
    max_people = serializers.SerializerMethodField()
    gaming_items = serializers.SerializerMethodField()

    class Meta:
        model = ComboPack
        fields = [
            "id",
            "name",
            "description",
            "combo_price",
            "snack_name",
            "snack_price",
            "loyalty_bonus",
            "max_people",
            "gaming_items",
            "image",
        ]

    def get_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "image", None))

    def get_combo_price(self, obj):
        return combo_price(obj)

    def get_snack_name(self, obj):
        return getattr(obj, "snack_name", None)

    def get_snack_price(self, obj):
        return getattr(obj, "snack_price", None)

    def get_loyalty_bonus(self, obj):
        return getattr(obj, "loyalty_bonus", 0)

    def get_gaming_items(self, obj):
        manager = getattr(obj, "gaming_items", None) or getattr(obj, "items", None)
        if not manager:
            return []
        items = manager.all() if hasattr(manager, "all") else manager
        return ComboGamingItemSerializer(items, many=True, context=self.context).data
    
    def get_description(self, obj):
        for field_name in ("description", "details", "short_description"):
            value = getattr(obj, field_name, None)
            if value:
                return value
        return ""
    
    def get_max_people(self, obj):
        return combo_max_people(obj)


class UserComboPackDetailSerializer(UserComboPackSerializer):
    pass


class CreateComboBookingSerializer(serializers.Serializer):
    combo_pack = serializers.UUIDField()
    booking_date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    members = BookingComboMemberSerializer(many=True, required=False, allow_empty=True)

    def validate(self, attrs):
        combo = ComboPack.objects.filter(
            id=attrs["combo_pack"],
            is_active=True,
            is_deleted=False,
        ).first()
        if not combo:
            raise serializers.ValidationError({"combo_pack": "Active combo pack not found."})

        today = timezone.localdate()
        if attrs["booking_date"] < today:
            raise serializers.ValidationError({"booking_date": "Booking date cannot be in the past."})

        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        if (
            attrs["booking_date"] == today
            and attrs["start_time"]
            <= timezone.localtime().time().replace(tzinfo=None)
        ):
            raise serializers.ValidationError(
                {"start_time": "Booking start time must be in the future."}
            )

        members = attrs.get("members", [])
        total_people = len(members) + 1
        max_people = combo_max_people(combo)
        if total_people > max_people:
            raise serializers.ValidationError({"members": f"Maximum {max_people} people allowed."})

        attrs["combo"] = combo
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        combo = validated_data["combo"]
        members = validated_data.get("members", [])
        total_price = combo_price(combo) or Decimal("0.00")
        start_time = validated_data["start_time"]
        end_time = validated_data["end_time"]
        start_seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
        end_seconds = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
        total_hours = Decimal(str(round((end_seconds - start_seconds) / 3600, 2)))
        try:
            booking = Booking.objects.create(
                user=request.user,
                combo_pack=combo,
                booking_date=validated_data["booking_date"],
                start_time=start_time,
                end_time=end_time,
                total_hours=total_hours,
                subtotal=total_price,
                discount_amount=Decimal("0.00"),
                total_amount=total_price,
                price_paid=Decimal("0.00"),
                loyalty_points_earned=combo.loyalty_bonus or 0,
                status=Booking.Status.PENDING,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"detail": exc.messages[0]}) from exc
        BookingMember.objects.bulk_create(
            [
                BookingMember(booking=booking, name=m["name"].strip(), phone=m.get("phone") or "")
                for m in members
            ]
        )
        return booking


class UserComboBookingSerializer(serializers.ModelSerializer):
    combo_name = serializers.CharField(source="combo_pack.name", read_only=True)
    combo_image = serializers.SerializerMethodField()
    qr_code = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    members = BookingComboMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "combo_name",
            "combo_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "total_amount",
            "member_count",
            "members",
            "qr_code",
            "qr_token",
            "checked_in",
            "checked_in_at",
            "created_at",
        ]

    def get_combo_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj.combo_pack, "image", None))

    def get_qr_code(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "qr_code", None))

    def get_member_count(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {})
        if "members" in prefetched:
            return len(prefetched["members"]) + 1
        return obj.members.count() + 1
