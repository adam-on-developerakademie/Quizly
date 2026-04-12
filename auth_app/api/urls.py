from django.urls import path
from .views import RegistrationView, CookieTokenObtainPairView, CookieTokenRefreshView, HelloWorld, LogoutView

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='registration'),
    path('login/', CookieTokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('hello/', HelloWorld.as_view(), name='hello'),
    path('logout/', LogoutView.as_view(), name='logout'),
]