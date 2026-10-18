"""Public home page and terms views."""

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from gaming.models import (
    ComboPack,
    CustomUser,
    ExclusiveEvent,
    GameCategory,
    GamingItem,
    TermsAndConditions,
)
from gaming.serializers import HomeSerializer, TermsSerializer
from gaming.utils.image_encryption import safe_image_to_data_uri


class PublicHomeAPIView(APIView):
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_home"

    def get(self, request):
        now = timezone.localtime()

        # -----------------------
        # Events
        # -----------------------

        events = (
                ExclusiveEvent.objects.filter(
                    is_active=True,
                    is_deleted=False,
                )
                .filter(
                    Q(event_date__gt=now.date())
                    | Q(
                        event_date=now.date(),
                        end_time__gte=now.time(),
                    )
                )
                .order_by("event_date", "start_time")[:5]
            )

        # -----------------------
        # Combo Packs
        # -----------------------

        combos = ComboPack.objects.filter(
            is_active=True,
            is_deleted=False,
        ).prefetch_related(
            "gaming_items"
        )[:8]

        # -----------------------
        # Categories + Games
        # -----------------------

        categories = (
            GameCategory.objects.filter(is_active=True, is_deleted=False)
            .prefetch_related("gaming_items")
            .order_by("name")
        )

        # -----------------------
        # Featured Games
        # -----------------------

        featured_games = GamingItem.objects.filter(
            is_active=True,
            is_deleted=False,
            maintenance_mode=False,
        )

        # -----------------------
        # Banner Priority
        # -----------------------

        banners = []

        for event in events:

            banners.append(
                {
                    "id": event.id,
                    "title": event.title,
                    "subtitle": event.description,
                    "image": (
                        safe_image_to_data_uri(event.image)
                        if event.image
                        else None
                    ),
                    "type": "event",
                    "action_url": f"/events/{event.id}",
                }
            )

        for game in featured_games:

            banners.append(
                {
                    "id": game.id,
                    "title": game.name,
                    "subtitle": game.description,
                    "image": (
                        safe_image_to_data_uri(game.image)
                        if game.image
                        else None
                    ),
                    "type": "game",
                    "action_url": f"/games/{game.id}",
                }
            )

        # -----------------------
        # Statistics
        # -----------------------

        stats = {
            "total_users": CustomUser.objects.filter(
                role=CustomUser.Role.USER,
                is_active=True,
                is_deleted=False,
            ).count(),
            "total_games": GamingItem.objects.filter(
                is_active=True,
                is_deleted=False,
            ).count(),
            "total_events": ExclusiveEvent.objects.filter(
                is_active=True,
                is_deleted=False,
            ).count(),
            "total_combo_packs": ComboPack.objects.filter(
                is_active=True,
                is_deleted=False,
            ).count(),
        }

        serializer = HomeSerializer(
            {
                "banners": banners,
                "events": events,
                "combo_packs": combos,
                "categories": categories,
                "stats": stats,
            },
            context={
                "request": request,
            },
        )

        return Response(
            {
                "success": True,
                "data": serializer.data,
            }
        )


class TermsAPIView(APIView):

    permission_classes = [AllowAny]

    def get(self, request):

        terms = (
            TermsAndConditions.objects
            .filter(
                is_current=True,
                is_active=True,
                is_deleted=False,
            )
            .first()
        )

        if not terms:

            return Response(
                {
                    "detail": "Terms & Conditions not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = TermsSerializer(
            terms,
            context={"request": request}
        )

        return Response(serializer.data)
