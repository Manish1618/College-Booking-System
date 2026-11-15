from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import RoomPhotoViewSet, RoomTypeViewSet, RoomViewSet

router = SimpleRouter(trailing_slash=False)
router.register("room-types", RoomTypeViewSet, basename="room-type")
router.register("rooms", RoomViewSet, basename="room")
urlpatterns = router.urls + [
    path("photos/<uuid:pk>", RoomPhotoViewSet.as_view({"patch": "partial_update", "delete": "destroy"})),
]
