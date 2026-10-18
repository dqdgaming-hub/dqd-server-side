"""Serializers backing the admin dashboard."""

from rest_framework import serializers

from gaming.models import Booking, CustomUser, GamingItem, UserDevice
from gaming.utils.image_encryption import safe_image_to_data_uri


class AdminDashboardBookingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "user_name",
            "user_email",
            "booking_date",
            "status",
            "total_amount",
        ]


class AdminDashboardUserSerializer(serializers.ModelSerializer):

    full_name = serializers.CharField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(source="is_online_flag", read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "full_name",
            "email",
            "is_active",
            "profile_image_url",
            "created_at",
            "is_online",
        ]

    def get_profile_image_url(self, user):
        if not user.profile_image:
            return None

        return safe_image_to_data_uri(user.profile_image)

    def get_is_online(self, user):
        device = (
            UserDevice.objects.filter(
                user=user,
                is_deleted=False,
            )
            .order_by("-last_seen")
            .first()
        )
        return device.is_online if device else False


class AdminDashboardDeviceSerializer(serializers.ModelSerializer):

    # is_online = serializers.BooleanField(
    #     source="is_online_flag",
    #     read_only=True
    # )
    is_online = serializers.BooleanField(source="is_currently_online", read_only=True)
    user = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = UserDevice
        fields = [
            "id",
            "device_id",
            "ip_address",
            "user",
            "browser",
            "operating_system",
            "device_name",
            "device_type",
            "login_at",
            "last_seen",
            "logged_out_at",
            "is_online",
        ]


class AdminDashboardGamingItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    reason = serializers.SerializerMethodField()

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "category_name",
            "reason",
        ]

    def get_reason(self, item):
        if item.maintenance_mode:
            return "Maintenance mode enabled."
        if not item.is_active:
            return "Gaming item is inactive."
        return "This gaming item needs attention."
