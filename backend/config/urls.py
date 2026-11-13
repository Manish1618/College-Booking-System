from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.accounts.urls import user_urlpatterns


def healthz(request):
    return JsonResponse({"status": "ok"})


api = [
    path("healthz", healthz),
    path("auth/", include("apps.accounts.urls")),
    path("", include(user_urlpatterns)),
    path("", include("apps.rooms.urls")),
    path("", include("apps.bookings.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.audit.urls")),
]
if settings.OIDC_ENABLED:
    api.append(path("auth/oidc/", include("mozilla_django_oidc.urls")))

urlpatterns = [
    path("api/", include(api)),
    path("django-admin/", admin.site.urls),
]
if settings.DEBUG and not settings.S3_ENABLED:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
