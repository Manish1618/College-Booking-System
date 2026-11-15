from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "phone", "role", "department", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["name", "email", "phone"]
    exclude = ["password", "groups", "user_permissions", "is_superuser"]
    readonly_fields = ["last_login", "date_joined", "sso_subject"]
