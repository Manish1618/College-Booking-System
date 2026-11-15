from django.contrib import admin

from .models import ApprovalRule, Booking, RegisterEntry


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Read-only: status changes must go through the state machine so they are validated and logged."""

    list_display = ["reference", "requester", "room_type", "room", "check_in", "check_out", "status"]
    list_filter = ["status", "category", "room_type"]
    search_fields = ["reference"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ApprovalRule)


@admin.register(RegisterEntry)
class RegisterEntryAdmin(BookingAdmin):
    list_display = ["serial_number", "guest", "room", "arrival_at", "departure_at"]
    list_filter = []
    search_fields = ["guest__name"]
