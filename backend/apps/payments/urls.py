from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("refunds", views.RefundViewSet, basename="refund")
urlpatterns = router.urls + [
    path("payments/gateways", views.GatewaysView.as_view()),
    path("payments/webhooks/<slug:gateway>", views.WebhookView.as_view()),
    path("payments/dev/complete", views.DevCompleteView.as_view()),
    path("payments/mobikwik/return", views.MobikwikReturnView.as_view()),
    path("bookings/<uuid:pk>/pay", views.PayView.as_view()),
    path("bookings/<uuid:pk>/payment-status", views.PaymentStatusView.as_view()),
    path("bookings/<uuid:pk>/refunds", views.BookingRefundView.as_view()),
    path("bookings/<uuid:pk>/receipt.pdf", views.ReceiptView.as_view()),
]
