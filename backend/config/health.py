from django.http import JsonResponse

HEALTH_PATH = "/api/healthz"


class HealthCheckMiddleware:
    """Answers the container health probe before the host and HTTPS checks run.

    The probe calls the app on localhost from inside the container. In production ALLOWED_HOSTS holds
    only the public domain, so the same request sent through the normal stack would be refused with a
    400 and the stack would never come up. The reply carries no data and touches nothing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH:
            return JsonResponse({"status": "ok"})
        return self.get_response(request)
