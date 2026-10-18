"""User-facing game catalog serializers."""

from rest_framework import serializers

from gaming.models import GameCategory, GamingItem
from gaming.serializers.common import EncryptedImageField
from gaming.utils.image_encryption import safe_image_to_data_uri


class UserGameCategorySerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    class Meta:
        model = GameCategory
        fields = [
            "id",
            "name",
            "category_type",
            "image",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return safe_image_to_data_uri(obj.image)
        return None


class UserGamingItemListSerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    category = serializers.CharField(source="category.name", read_only=True)

    category_id = serializers.UUIDField(source="category.id", read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "category",
            "category_id",
            "description",
            "image",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "maintenance_mode",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return safe_image_to_data_uri(obj.image)
        return None


class UserGamingItemDetailSerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    category = UserGameCategorySerializer(read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "category",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "maintenance_mode",
            "created_at",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return safe_image_to_data_uri(obj.image)
        return None


class UserGamingItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    image = EncryptedImageField(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "image_url",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "category",
            "category_name",
        ]

    def get_image_url(self, obj):
        return safe_image_to_data_uri(obj.image)
