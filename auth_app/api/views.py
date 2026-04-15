import logging

from rest_framework import status
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import (
    AccessToken,
    RefreshToken,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from rest_framework.views import APIView

from auth_app.models import RevokedToken
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegistrationSerializer,
)
from .utils import (
    clear_auth_cookies,
    get_token_time_info,
    revoke_token,
    set_auth_cookies,
)


logger = logging.getLogger(__name__)


class RegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            return Response(
                {"error": "Authenticated users cannot create a new account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RegistrationSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"detail": "User created successfully!"},
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class HelloWorld(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        access_token = request.COOKIES.get("access_token")
        refresh_token = request.COOKIES.get("refresh_token")

        return Response(
            {
                "message": "Hello {}".format(request.user.username),
                "email": request.user.email,
                "user_id": request.user.pk,
                "access_token_info": get_token_time_info(
                    access_token,
                    AccessToken,
                ),
                "refresh_token_info": get_token_time_info(
                    refresh_token,
                    RefreshToken,
                ),
            }
        )


class CookieTokenObtainPairView(TokenObtainPairView):

    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serialiser = self.get_serializer(data=request.data)
        serialiser.is_valid(raise_exception=True)

        user = serialiser.user
        response = Response(
            {
                "detail": "Login successfully!",
                "user": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                },
            }
        )
        refresh = serialiser.validated_data["refresh"]
        access = serialiser.validated_data["access"]

        response = set_auth_cookies(
            response,
            access_token=access,
            refresh_token=refresh,
        )

        return response


class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")
        if not refresh_token:
            return Response(
                {"error": "No refresh token provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh_obj = RefreshToken(refresh_token)
        except TokenError:
            return Response(
                {"error": "Invalid refresh token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh_jti = refresh_obj.get("jti")
        if (
            refresh_jti
            and RevokedToken.objects.filter(jti=refresh_jti).exists()
        ):
            return Response(
                {"error": "Refresh token has been revoked"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data = {"refresh": refresh_token}
        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        access = serializer.validated_data.get("access")

        response = Response({"detail": "Token refreshed"})
        response = set_auth_cookies(response, access_token=access)

        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        source_ip = request.META.get("REMOTE_ADDR")
        access_token = request.COOKIES.get("access_token")
        refresh_token = request.COOKIES.get("refresh_token")

        revoked_access = revoke_token(access_token, AccessToken, source_ip)
        revoked_refresh = revoke_token(refresh_token, RefreshToken, source_ip)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                # Blacklist table may already contain this token or token can
                # be invalid.
                pass

        logger.info(
            "Logout processed. access_revoked=%s refresh_revoked=%s ip=%s",
            revoked_access,
            revoked_refresh,
            source_ip,
        )

        response = Response(
            {
                "detail": (
                    "Log-Out successfully! All Tokens will be deleted. "
                    "Refresh token is now invalid."
                )
            },
            status=status.HTTP_200_OK,
        )
        response = clear_auth_cookies(response)
        return response
