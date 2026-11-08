from datetime import timedelta

from django.contrib import admin
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DeviceSession, User


class DeviceSessionInline(admin.TabularInline):
    model = DeviceSession
    extra = 0
    fields = ("device_name", "platform", "created_at", "last_seen_at", "revoked_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = False


class BoughtFilter(admin.SimpleListFilter):
    title = "خرید کرده"
    parameter_name = "bought"

    def lookups(self, request, model_admin):
        return [("1", "بله"), ("0", "خیر")]

    def queryset(self, request, queryset):
        from apps.commerce.models import Order

        paid = Order.objects.filter(status=Order.Status.PAID).values("user_id")
        if self.value() == "1":
            return queryset.filter(pk__in=paid)
        if self.value() == "0":
            return queryset.exclude(pk__in=paid)
        return queryset


class ActiveWeekFilter(admin.SimpleListFilter):
    """Opened the app (a signed-in device was seen) or studied in the last seven days."""

    title = "فعال در هفته‌ی گذشته"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        return [("1", "بله"), ("0", "خیر")]

    def queryset(self, request, queryset):
        from apps.study.models import StudyDay

        since = timezone.now() - timedelta(days=7)
        seen = DeviceSession.objects.filter(last_seen_at__gte=since).values("user_id")
        studied = StudyDay.objects.filter(date__gte=since.date()).values("user_id")
        active = Q(pk__in=seen) | Q(pk__in=studied)
        if self.value() == "1":
            return queryset.filter(active)
        if self.value() == "0":
            return queryset.exclude(active)
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "full_name", "email", "is_active", "date_joined")
    search_fields = ("phone", "email", "first_name", "last_name")
    list_filter = (BoughtFilter, ActiveWeekFilter, "date_joined", "is_active", "is_staff")
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
