import logging
from datetime import datetime, timezone

from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .serializers import RegistrationSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from auth_app.models import RevokedToken


logger = logging.getLogger(__name__)


def _exp_to_datetime(exp):
    if exp is None:
        return None
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def _revoke_token(raw_token, token_class, source_ip):
    if not raw_token:
        return None

    try:
        token = token_class(raw_token)
    except TokenError:
        return None

    token_jti = token.get("jti")
    user_id = token.get("user_id")
    expires_at = _exp_to_datetime(token.get("exp"))

    if token_jti:
        RevokedToken.objects.get_or_create(
            jti=token_jti,
            defaults={
                "token_type": token.get("token_type", "unknown"),
                "user_id": user_id,
                "expires_at": expires_at,
                "source_ip": source_ip,
            },
        )

    return {"jti": token_jti, "user_id": user_id}


class RegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)

        data = {}
        if serializer.is_valid():
            saved_account = serializer.save()
            data = {
                "username": saved_account.username,
                "email": saved_account.email,
                "user_id": saved_account.pk,
            }
            return Response(data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class HelloWorld(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "message": "Hello {}".format(request.user.username),
                "email": request.user.email,
                "user_id": request.user.pk,
            }
        )


from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .serializers import CustomTokenObtainPairSerializer


class CookieTokenObtainPairView(TokenObtainPairView):

    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serialiser = self.get_serializer(data=request.data)
        serialiser.is_valid(raise_exception=True)

        response = Response({"message": "Login mit email erfolgreich"})
        refresh = serialiser.validated_data["refresh"]
        access = serialiser.validated_data["access"]

        cookie_secure = settings.JWT_COOKIE_SECURE

        response.set_cookie(
            key="access_token",
            value=str(access),
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
        )
        response.set_cookie(
            key="refresh_token",
            value=str(refresh),
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
        )
        response.data = {"message": "Tokens set in cookies"}

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
            return Response({"error": "Invalid refresh token"}, status=status.HTTP_400_BAD_REQUEST)

        refresh_jti = refresh_obj.get("jti")
        if refresh_jti and RevokedToken.objects.filter(jti=refresh_jti).exists():
            return Response({"error": "Refresh token has been revoked"}, status=status.HTTP_401_UNAUTHORIZED)

        data = {"refresh": refresh_token}
        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        access = serializer.validated_data.get("access")

        # Setzen Sie das neue Access-Token als HttpOnly-Cookie
        cookie_secure = settings.JWT_COOKIE_SECURE
        response = Response({"message": "Access token refreshed and set in cookie"})
        response.set_cookie(
            key="access_token",
            value=access,
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
        )

        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        cookie_secure = settings.JWT_COOKIE_SECURE
        source_ip = request.META.get("REMOTE_ADDR")
        access_token = request.COOKIES.get("access_token")
        refresh_token = request.COOKIES.get("refresh_token")

        revoked_access = _revoke_token(access_token, AccessToken, source_ip)
        revoked_refresh = _revoke_token(refresh_token, RefreshToken, source_ip)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                # Blacklist table may already contain this token or token can be invalid.
                pass

        logger.info(
            "Logout processed. access_revoked=%s refresh_revoked=%s ip=%s",
            revoked_access,
            revoked_refresh,
            source_ip,
        )

        response = Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)
        response.set_cookie(
            key="access_token",
            value="",
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
            max_age=0,
        )
        response.set_cookie(
            key="refresh_token",
            value="",
            httponly=True,
            secure=cookie_secure,
            samesite="Lax",
            max_age=0,
        )
        return response
