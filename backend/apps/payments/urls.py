from django.urls import path

from .views import GatewaysView, PayView

urlpatterns = [
    path("payments/gateways", GatewaysView.as_view()),
    path("bookings/<uuid:pk>/pay", PayView.as_view()),
]
