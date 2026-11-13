from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ApprovalRuleViewSet, AvailabilityView, BookingViewSet, DocumentDownloadView

router = SimpleRouter(trailing_slash=False)
router.register("bookings", BookingViewSet, basename="booking")
router.register("approval-rules", ApprovalRuleViewSet, basename="approval-rule")
urlpatterns = router.urls + [
    path("availability", AvailabilityView.as_view()),
    path("documents/<uuid:pk>/download", DocumentDownloadView.as_view()),
]
