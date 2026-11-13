from django.contrib import admin

from .models import Room, RoomType, Tariff


class TariffInline(admin.TabularInline):
    model = Tariff
    extra = 0


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "capacity", "is_active"]
    inlines = [TariffInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["number", "room_type", "floor", "is_active"]
    list_filter = ["room_type", "is_active"]
