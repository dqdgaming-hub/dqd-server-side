"""Happy-hour and spinner-reward serializers."""

from rest_framework import serializers

from gaming.models import (
    HappyHourAllocation,
    HappyHourBooking,
    HappyHourTemplateSlot,
    SpinnerReward,
)


class HappyHourTemplateSlotSerializer(serializers.ModelSerializer):

    weekday_display = serializers.CharField(
        source="get_weekday_display",
        read_only=True,
    )

    class Meta:
        model = HappyHourTemplateSlot
        fields = "__all__"


class SpinnerRewardSerializer(serializers.ModelSerializer):

    template_slot_name = serializers.CharField(
        source="template_slot.slot_name",
        read_only=True,
    )

    class Meta:
        model = SpinnerReward
        fields = "__all__"


class HappyHourBookingSerializer(serializers.ModelSerializer):

    user_name = serializers.CharField(
        source="happy_hour_slot.user.full_name",
        read_only=True,
    )

    slot_name = serializers.CharField(
        source="happy_hour_slot.template_slot.slot_name",
        read_only=True,
    )

    game_name = serializers.CharField(
        source="booking.item.name",
        read_only=True,
    )

    class Meta:
        model = HappyHourBooking
        fields = "__all__"


class AdminAssignHappyHourGameSerializer(serializers.Serializer):
    gaming_item = serializers.UUIDField()


class HappyHourAllocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = HappyHourAllocation
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "offer_percentage",
            "loyalty_points",
            "is_free",
            "max_bookings",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):

        start_time = attrs.get(
            "start_time",
            getattr(self.instance, "start_time", None)
        )

        end_time = attrs.get(
            "end_time",
            getattr(self.instance, "end_time", None)
        )

        offer_percentage = attrs.get(
            "offer_percentage",
            getattr(self.instance, "offer_percentage", 0)
        )

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({
                "end_time": "End time must be after start time."
            })

        if offer_percentage > 100:
            raise serializers.ValidationError({
                "offer_percentage": "Offer percentage cannot exceed 100."
            })

        return attrs


class UserHappyHourAllocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = HappyHourAllocation
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "offer_percentage",
            "is_free",
            "max_bookings",
            "is_active",
            "notes",
        ]
