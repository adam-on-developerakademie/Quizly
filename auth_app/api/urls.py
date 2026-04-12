from django.urls import path
from .views import RegistrationView, CookieTokenObtainPairView, CookieTokenRefreshView, HelloWorld, LogoutView

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='registration'),
    path('token/', CookieTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('hello/', HelloWorld.as_view(), name='hello'),
    path('logout/', LogoutView.as_view(), name='logout'),
]