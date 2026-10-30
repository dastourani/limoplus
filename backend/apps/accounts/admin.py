from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DeviceSession, User


class DeviceSessionInline(admin.TabularInline):
    model = DeviceSession
    extra = 0
    fields = ("device_name", "platform", "created_at", "last_seen_at", "revoked_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "full_name", "email", "is_active", "date_joined")
    search_fields = ("phone", "email", "first_name", "last_name")
    list_filter = ("is_active", "is_staff")
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("مشخصات", {"fields": ("first_name", "last_name", "email")}),
        ("دسترسی", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),)
    inlines = [DeviceSessionInline]


@admin.register(DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "platform", "last_seen_at", "revoked_at")
    list_filter = ("platform",)
    search_fields = ("user__phone", "device_name")
    readonly_fields = ("user", "device_name", "platform", "created_at", "last_seen_at", "expires_at", "revoked_at")
    exclude = ("token_hash",)
    actions = ["revoke_sessions"]

    @admin.action(description="خارج کردن نشست‌های انتخاب‌شده")
    def revoke_sessions(self, request, queryset):
        for session in queryset:
            session.revoke()

    def has_add_permission(self, request):
        return False
