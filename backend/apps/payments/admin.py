from django.contrib import admin

from .models import Payment, Refund


class ReadOnly(admin.ModelAdmin):
    """Money records are changed only by the payment code, never by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnly):
    list_display = ["order_id", "booking", "gateway", "amount", "status", "refunded_amount", "paid_at"]
    list_filter = ["gateway", "status"]
    search_fields = ["order_id", "gateway_payment_id", "booking__reference"]


@admin.register(Refund)
class RefundAdmin(ReadOnly):
    list_display = ["payment", "amount", "status", "manual", "reason", "created_at", "processed_at"]
    list_filter = ["status", "manual"]
    search_fields = ["payment__order_id", "payment__booking__reference", "gateway_refund_id"]
