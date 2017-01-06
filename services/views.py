from django.contrib.auth.models import User, Group
from .models import Service, Status, UserServiceToken
from .tasks import get_user_token
from rest_hooks.models import Hook
from rest_framework import filters, status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .serializers import (UserSerializer, GroupSerializer,
                          ServiceSerializer, StatusSerializer, HookSerializer,
                          UserServiceTokenSerializer,
                          UserTokenRequestSerializer)


class HookViewSet(viewsets.ModelViewSet):
    """
    Retrieve, create, update or destroy webhooks.
    """
    permission_classes = (IsAuthenticated,)
    queryset = Hook.objects.all()
    serializer_class = HookSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class UserViewSet(viewsets.ReadOnlyModelViewSet):

    """
    API endpoint that allows users to be viewed or edited.
    """
    permission_classes = (IsAdminUser,)
    queryset = User.objects.all()
    serializer_class = UserSerializer


class GroupViewSet(viewsets.ReadOnlyModelViewSet):

    """
    API endpoint that allows groups to be viewed or edited.
    """
    permission_classes = (IsAdminUser,)
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


class ServiceViewSet(viewsets.ModelViewSet):

    """
    API endpoint that allows dummy models to be viewed or edited.
    """
    permission_classes = (IsAuthenticated,)
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user,
                        updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class StatusViewSet(viewsets.ReadOnlyModelViewSet):

    """
    API endpoint that allows dummy models to be viewed or edited.
    """
    permission_classes = (IsAuthenticated,)
    queryset = Status.objects.all()
    serializer_class = StatusSerializer
    filter_backends = (filters.OrderingFilter, filters.DjangoFilterBackend)
    filter_fields = ('service', 'up',)
    ordering_fields = ('created_at',)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user,
                        updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class UserServiceTokenViewSet(viewsets.ReadOnlyModelViewSet):

    """
    API endpoint that allows user service tokens to be viewed
    """
    permission_classes = (IsAuthenticated,)
    queryset = UserServiceToken.objects.all()
    serializer_class = UserServiceTokenSerializer
    filter_backends = (filters.DjangoFilterBackend, )
    filter_fields = ('service', 'user_id', 'email', )


class UserServiceTokenTriggerView(APIView):

    """ UserServiceToken population - admin users only
        POST - starts up the task that fires all the scheduled metrics
    """
    permission_classes = (IsAdminUser,)

    def post(self, request, *args, **kwargs):
        serializer = UserTokenRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data.get('email')
        user_id = serializer.validated_data.get('user_id')
        services = Service.objects.all()
        for service in services:
            get_user_token.apply_async(kwargs={
                "service_id": str(service.id),
                "user_id": user_id,
                "email": email
            })
        resp = {
            "user_service_token_initiated": True,
            "count": services.count()
        }
        return Response(
            status=status.HTTP_201_CREATED, data=resp)
