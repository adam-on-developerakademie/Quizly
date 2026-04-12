from rest_framework_simplejwt.authentication import JWTAuthentication
from auth_app.models import RevokedToken


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using JWT from HttpOnly cookie as a fallback."""

    def authenticate(self, request):
        header = self.get_header(request)

        if header is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get("access_token")
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        token_jti = validated_token.get("jti")
        if token_jti and RevokedToken.objects.filter(jti=token_jti).exists():
            return None
        return self.get_user(validated_token), validated_token
