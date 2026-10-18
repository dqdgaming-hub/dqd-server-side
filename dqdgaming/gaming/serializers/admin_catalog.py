"""Admin CRUD serializers for categories, games, combo packs and events."""

from rest_framework import serializers

from gaming.models import ComboPack, ExclusiveEvent, GameCategory, GamingItem
from gaming.serializers.common import EncryptedImageField
from gaming.utils.image_encryption import safe_image_to_data_uri


class AdminGameCategorySerializer(serializers.ModelSerializer):

    image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = GameCategory
        fields = "__all__"


class AdminGamingItemSerializer(serializers.ModelSerializer):

    category_name = serializers.CharField(source="category.name", read_only=True)

    image = EncryptedImageField(
            required=False,
            allow_null=True,
        )

    class Meta:
        model = GamingItem
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["image"] = safe_image_to_data_uri(instance.image)
        return data


class AdminComboPackSerializer(serializers.ModelSerializer):

    image = EncryptedImageField(required=False, allow_null=True)

    gaming_items = serializers.PrimaryKeyRelatedField(
        many=True, queryset=GamingItem.objects.all()
    )

    class Meta:
        model = ComboPack
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["image"] = safe_image_to_data_uri(instance.image)
        return data


class AdminExclusiveEventSerializer(serializers.ModelSerializer):

    image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = ExclusiveEvent
        fields = "__all__"

    def create(self, validated_data):
        validated_data["is_active"] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["is_active"] = True
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["image"] = safe_image_to_data_uri(instance.image)
        return data
