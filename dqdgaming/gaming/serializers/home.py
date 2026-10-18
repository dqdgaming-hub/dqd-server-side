"""Public home page and terms serializers."""

from rest_framework import serializers

from gaming.models import (
    ComboPack,
    ExclusiveEvent,
    GameCategory,
    GamingItem,
    TermsAndConditions,
)
from gaming.utils.image_encryption import safe_image_to_data_uri


class HomeEventSerializer(serializers.ModelSerializer):

    available_slots = serializers.ReadOnlyField()
    image = serializers.SerializerMethodField()

    class Meta:

        model = ExclusiveEvent

        fields = (
            "id",
            "title",
            "description",
            "event_date",
            "start_time",
            "end_time",
            "price",
            "available_slots",
            "image",
        )

    def get_image(self, obj):
        return safe_image_to_data_uri(obj.image)


class HomeComboSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:

        model = ComboPack

        fields = (
            "id",
            "name",
            "combo_price",
            "snack_name",
            "image",
            "loyalty_bonus",
        )

    def get_image(self, obj):
        return safe_image_to_data_uri(obj.image)


class HomeGameSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:

        model = GamingItem

        fields = (
            "id",
            "name",
            "image",
            "price_per_hour",
            "max_capacity",
            "maintenance_mode",
        )

    def get_image(self, obj):
        return safe_image_to_data_uri(obj.image)


class HomeCategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    games = HomeGameSerializer(
        source="gaming_items",
        many=True,
    )

    class Meta:

        model = GameCategory

        fields = (
            "id",
            "name",
            "category_type",
            "image",
            "games",
        )

    def get_image(self, obj):
        return safe_image_to_data_uri(obj.image)


class HomeStatsSerializer(serializers.Serializer):

    total_users = serializers.IntegerField()

    total_games = serializers.IntegerField()

    total_events = serializers.IntegerField()

    total_combo_packs = serializers.IntegerField()


class HomeSerializer(serializers.Serializer):

    banners = serializers.ListField()

    events = HomeEventSerializer(many=True)

    combo_packs = HomeComboSerializer(many=True)

    categories = HomeCategorySerializer(many=True)

    stats = HomeStatsSerializer()


class TermsSerializer(serializers.ModelSerializer):

    class Meta:
        model = TermsAndConditions
        fields = (
            "id",
            "version",
            "title",
            "content",
            "effective_date",
        )
