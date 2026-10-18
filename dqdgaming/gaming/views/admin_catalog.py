"""Admin CRUD views for categories, games, combo packs and events."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import ComboPack, ExclusiveEvent, GameCategory, GamingItem
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminComboPackSerializer,
    AdminExclusiveEventSerializer,
    AdminGameCategorySerializer,
    AdminGamingItemSerializer,
)


class AdminCategoryListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):
        serializer = AdminGameCategorySerializer(
            GameCategory.objects.all(),
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    def post(self, request):
        serializer = AdminGameCategorySerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AdminGameListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):

        serializer = AdminGamingItemSerializer(
            GamingItem.objects.select_related("category"),
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    def post(self, request):

        serializer = AdminGamingItemSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=201)


class AdminComboPackListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):

        serializer = AdminComboPackSerializer(
            ComboPack.objects.prefetch_related("gaming_items"),
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    def post(self, request):

        serializer = AdminComboPackSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=201)


class AdminEventListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):

        serializer = AdminExclusiveEventSerializer(
            ExclusiveEvent.objects.all(),
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    def post(self, request):

        serializer = AdminExclusiveEventSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=201)


class AdminGameDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def put(self, request, pk):

        game = get_object_or_404(GamingItem, pk=pk)

        serializer = AdminGamingItemSerializer(
            game,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)

    def delete(self, request, pk):

        GamingItem.objects.filter(pk=pk).delete()

        return Response(status=204)


class AdminCategoryDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def put(self, request, pk):

        category = GameCategory.objects.get(pk=pk)

        serializer = AdminGameCategorySerializer(
            category,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)

    def delete(self, request, pk):

        GameCategory.objects.filter(pk=pk).delete()

        return Response(status=204)


class AdminComboPackDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def put(self, request, pk):

        combo = get_object_or_404(ComboPack, pk=pk)

        serializer = AdminComboPackSerializer(
            combo,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(serializer.data)

    def delete(self, request, pk):

        combo = get_object_or_404(ComboPack, pk=pk)

        combo.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminEventDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def put(self, request, pk):

        event = get_object_or_404(ExclusiveEvent, pk=pk)

        serializer = AdminExclusiveEventSerializer(
            event,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        serializer.save()

        return Response(serializer.data)

    def delete(self, request, pk):

        event = get_object_or_404(ExclusiveEvent, pk=pk)

        event.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
