"""Serializers backing the user dashboard."""

from rest_framework import serializers

from gaming.models import (
    Booking,
    BookingMember,
    ComboPack,
    ExclusiveEvent,
    GamingItem,
    SpinnerReward,
    SpinnerSpin,
)
from gaming.serializers.common import EncryptedImageField


class GameSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    image = EncryptedImageField(read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "price_per_hour",
            "category_name",
            "maintenance_mode",
        ]


class BookingMemberSerializers(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = [
            "id",
            "name",
            "phone",
            "is_admin_added",
        ]


class BookingSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    members = BookingMemberSerializers(
        many=True,
        read_only=True,
    )

    base_price = serializers.DecimalField(
        source="subtotal",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    discount_price = serializers.DecimalField(
        source="discount_amount",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    item_image = EncryptedImageField(source="item.image", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "item_name",
            "item_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "base_price",
            "discount_price",
            "total_amount",
            "members",
            "created_at",
            "is_qr_valid",
        ]


class ExclusiveEventSerializer(serializers.ModelSerializer):
    available_slots = serializers.ReadOnlyField()
    image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = ExclusiveEvent
        fields = [
            "id",
            "title",
            "description",
            "event_date",
            "start_time",
            "end_time",
            "price",
            "image",
            "available_slots",
        ]


class UserSpinnerRewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpinnerReward
        fields = [
            "id",
            "reward_name",
            "reward_type",
            "reward_points",
            "probability",
            "is_active",
        ]


class ComboPackSerializer(serializers.ModelSerializer):
    image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = ComboPack
        fields = [
            "id",
            "name",
            "snack_name",
            "snack_price",
            "combo_price",
            "loyalty_bonus",
            "image",
        ]


class SpinnerSpinSerializer(serializers.ModelSerializer):
    reward_name = serializers.CharField(
        source="reward.reward_name",
        read_only=True,
    )
    spin_date = serializers.SerializerMethodField()

    class Meta:
        model = SpinnerSpin
        fields = [
            "id",
            "reward_name",
            "spin_date",
            "spun_at",
        ]

    def get_spin_date(self, obj):
        return obj.spun_at.date().isoformat() if obj.spun_at else None
