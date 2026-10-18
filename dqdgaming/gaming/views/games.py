"""User-facing game catalog views."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import GameCategory, GamingItem
from gaming.serializers import (
    UserGameCategorySerializer,
    UserGamingItemDetailSerializer,
    UserGamingItemListSerializer,
    UserGamingItemSerializer,
)


class UserGameCategoryAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        categories = GameCategory.objects.filter(
            is_active=True,
            is_deleted=False,
        ).order_by("name")

        serializer = UserGameCategorySerializer(
            categories, many=True, context={"request": request}
        )

        return Response(
            {"success": True, "count": categories.count(), "results": serializer.data}
        )


class UserGameListAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        category = request.GET.get("category")
        search = request.GET.get("search")

        games = (
            GamingItem.objects.select_related("category")
            .filter(
                is_active=True,
                is_deleted=False,
                maintenance_mode=False,
            )
            .order_by("name")
        )

        if category:
            games = games.filter(category_id=category)

        if search:
            games = games.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        serializer = UserGamingItemListSerializer(
            games, many=True, context={"request": request}
        )

        return Response(
            {"success": True, "count": games.count(), "results": serializer.data}
        )


class UserGameDetailAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):

        game = get_object_or_404(
            GamingItem.objects.select_related("category"),
            pk=pk,
            is_active=True,
            is_deleted=False,
        )

        serializer = UserGamingItemDetailSerializer(game, context={"request": request})

        return Response({"success": True, "data": serializer.data})


class UserGamingItemListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        gaming_items = (
            GamingItem.objects.select_related("category")
            .filter(
                is_active=True,
                is_deleted=False,
                maintenance_mode=False,
            )
            .order_by("category__name", "name")
        )

        serializer = UserGamingItemSerializer(
            gaming_items,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)
