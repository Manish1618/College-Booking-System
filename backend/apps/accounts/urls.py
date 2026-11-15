from django.urls import path

from . import views

users = views.UserViewSet.as_view({"get": "list", "post": "create"})
user = views.UserViewSet.as_view({"get": "retrieve", "patch": "partial_update"})

urlpatterns = [
    path("csrf", views.CsrfView.as_view()),
    path("otp/request", views.OTPRequestView.as_view()),
    path("otp/verify", views.OTPVerifyView.as_view()),
    path("logout", views.LogoutView.as_view()),
    path("me", views.MeView.as_view()),
    path("totp/setup", views.TOTPSetupView.as_view()),
    path("totp/verify", views.TOTPVerifyView.as_view()),
]

user_urlpatterns = [
    path("users", users),
    path("users/<uuid:pk>", user),
    path("users/<uuid:pk>/reset-mfa", views.UserViewSet.as_view({"post": "reset_mfa"})),
]
