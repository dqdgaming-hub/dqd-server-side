"""Profile, navbar and signed-in device views."""

from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.middleware import DeviceActivityMixin
from gaming.models import UserDevice
from gaming.serializers import (
    NavbarUserSerializer,
    ProfileSerializer,
    UserDeviceSerializer,
    UserProfileSerializer,
)


class MyDevicesView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        devices = UserDevice.objects.filter(
            user=request.user,
            is_deleted=False,
        ).order_by("-last_seen")

        serializer = UserDeviceSerializer(
            devices,
            many=True,
            context={"request": request},
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class ProfileView(
    DeviceActivityMixin,
    generics.RetrieveUpdateAPIView,
):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


class NavbarProfileView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.is_active:
            return Response(
                {"detail": "This account has been deactivated."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.is_deleted:
            return Response(
                {"detail": "This account is no longer available."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NavbarUserSerializer(
            user,
            context={"request": request},
        )

        return Response(
            {"user": serializer.data},
            status=status.HTTP_200_OK,
        )


class ProfileAPIView(APIView):

    permission_classes = [
        IsAuthenticated,
    ]

    def get(self, request):

        serializer = ProfileSerializer(
            request.user,
            context={
                "request": request,
            },
        )

        return Response(serializer.data)

    def patch(self, request):

        serializer = ProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={
                "request": request,
            },
        )

        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        return Response(
            ProfileSerializer(
                user,
                context={"request": request},
            ).data
        )
