from django.urls import path, re_path
from rest_framework.routers import SimpleRouter

from .desk import DeskView, RegisterExportView, RegisterView
from .views import ApprovalRuleViewSet, AvailabilityView, BookingViewSet, DocumentDownloadView

router = SimpleRouter(trailing_slash=False)
router.register("bookings", BookingViewSet, basename="booking")
router.register("approval-rules", ApprovalRuleViewSet, basename="approval-rule")
urlpatterns = router.urls + [
    path("availability", AvailabilityView.as_view()),
    path("documents/<uuid:pk>/download", DocumentDownloadView.as_view()),
    path("desk", DeskView.as_view()),
    path("register", RegisterView.as_view()),
    re_path(r"^register\.(?P<kind>csv|pdf)$", RegisterExportView.as_view()),
]
