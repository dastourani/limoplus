from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DeviceSession, User


PLATFORMS = {"android": "اندروید", "ios": "آیفون", "web": "وب"}


def device_label(session) -> str:
    """One way of naming a device everywhere: «Samsung SM-A515F (اندروید)», «مرورگر وب»."""
    name = (session.device_name or "").strip()
    plat = (session.platform or "").strip().lower()
    if plat == "web" or name.lower() == "web" or name == "مرورگر وب":
        return "مرورگر وب"
    shown = PLATFORMS.get(plat, session.platform or "")
    if not name or name.lower() in PLATFORMS or name.lower() == "unknown":
        return f"گوشی {shown}" if shown else "دستگاه ناشناس"
    return f"{name} ({shown})" if shown else name


def session_state(session):
    from apps.catalog.jalali import jalali_date
    from apps.catalog.panel_display import badges

    if session.revoked_at:
        return badges((f"خارج شده {jalali_date(session.revoked_at)}", "grey"))
    if session.expires_at <= timezone.now():
        return badges(("منقضی", "grey"))
    return badges(("فعال", "green"))


class DeviceSessionInline(admin.TabularInline):
    model = DeviceSession
    extra = 0
    fields = ("device", "state", "created_at", "last_seen_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = False
    ordering = ("revoked_at", "-last_seen_at")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="دستگاه")
    def device(self, obj):
        return device_label(obj)

    @admin.display(description="وضعیت")
    def state(self, obj):
        return session_state(obj)


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
    """The list shows at a glance who buys and who studies; a user's page starts with «خلاصه»: access, orders and
    study, each with a link to its full list. Every number here is counted by the database with the list itself."""

    ordering = ("-date_joined",)
    list_display = ("who", "dates", "access", "paid", "study_month")
    list_display_links = ("who",)
    search_fields = ("phone", "email", "first_name", "last_name")
    list_filter = (BoughtFilter, ActiveWeekFilter, "date_joined", "is_active", "is_staff")
    readonly_fields = ("overview",)
    fieldsets = (
        ("خلاصه", {"fields": ("overview",)}),
        (None, {"fields": ("phone",)}),
        ("مشخصات", {"fields": ("first_name", "last_name", "email")}),
        ("دسترسی به پنل", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("گذرواژه‌ی پنل، گروه‌ها و اجازه‌های جزئی", {"classes": ("collapse",), "fields": ("password", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"classes": ("collapse",), "fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),)
    inlines = [DeviceSessionInline]

    def has_delete_permission(self, request, obj=None):
        # A learner's purchases, progress and notes must never be lost: «فعال» off signs them out instead.
        return False

    def get_queryset(self, request):
        from django.db.models import IntegerField, OuterRef, Subquery, Sum
        from django.db.models.functions import Coalesce

        from apps.commerce.models import Entitlement, Order
        from apps.study.models import StudyTime

        def one(qs, field):
            return Subquery(qs.order_by().values("user").annotate(v=field).values("v")[:1])

        now = timezone.now()
        mine = {"user": OuterRef("pk")}
        active = Entitlement.active_for_any(now).filter(**mine)
        return super().get_queryset(request).annotate(
            seen_at=Subquery(DeviceSession.objects.filter(**mine).order_by("-last_seen_at").values("last_seen_at")[:1]),
            n_books=Coalesce(one(active.filter(book__isnull=False), Count("pk")), 0),
            sub_until=Subquery(active.filter(book__isnull=True).order_by("-ends_at").values("ends_at")[:1]),
            sub_forever=Coalesce(one(active.filter(book__isnull=True, ends_at__isnull=True), Count("pk")), 0),
            paid_total=Coalesce(one(Order.objects.filter(status=Order.Status.PAID, **mine), Sum("amount")), 0,
                                output_field=IntegerField()),
            month_seconds=Coalesce(one(StudyTime.objects.filter(day__gte=now.date() - timedelta(days=30), **mine), Sum("seconds")),
                                   0, output_field=IntegerField()),
        )

    @admin.display(description="کاربر", ordering="phone")
    def who(self, obj):
        from django.utils.html import format_html

        name = obj.full_name
        return format_html('{} {}{}', obj.phone, self.flags(obj),
                           format_html('<div class="lp-quiet">{}</div>', name) if name else "")

    @admin.display(description="عضویت و آخرین بازدید", ordering="date_joined")
    def dates(self, obj):
        from django.utils.html import format_html

        from apps.catalog.jalali import jalali_date

        seen = jalali_date(obj.seen_at) if obj.seen_at else "—"
        return format_html('<span style="white-space:nowrap">{}</span><div class="lp-quiet" style="white-space:nowrap">'
                           'آخرین بازدید: {}</div>', jalali_date(obj.date_joined), seen)

    @admin.display(description="دسترسی")
    def access(self, obj):
        from apps.catalog.jalali import jalali_date
        from apps.catalog.panel_display import badges, fa_number

        sub = None
        if obj.sub_forever:
            sub = ("اشتراک همیشگی", "green")
        elif obj.sub_until:
            sub = (f"اشتراک تا {jalali_date(obj.sub_until)}", "green")
        return badges(sub, obj.n_books and (f"{fa_number(obj.n_books)} کتاب", "blue"))

    @admin.display(description="جمع خرید", ordering="paid_total")
    def paid(self, obj):
        from apps.commerce.admin import toman

        return toman(obj.paid_total) if obj.paid_total else "—"

    @admin.display(description="مطالعه در ۳۰ روز", ordering="month_seconds")
    def study_month(self, obj):
        from apps.catalog.panel_display import fa_number

        s = obj.month_seconds or 0
        if not s:
            return "—"
        if s < 3600:
            return f"{fa_number(max(1, round(s / 60)))} دقیقه"
        return f"{fa_number(round(s / 3600, 1))} ساعت"

    def flags(self, obj):
        from apps.catalog.panel_display import badges

        shown = badges(obj.is_superuser and ("مدیر کل", "yellow"), obj.is_staff and not obj.is_superuser and ("مدیر", "yellow"),
                       not obj.is_active and ("غیرفعال", "grey"))
        return "" if shown == "—" else shown

    @admin.display(description="")
    def overview(self, obj):
        from .overview import user_overview

        return user_overview(obj) if obj and obj.pk else "—"


class SessionStateFilter(admin.SimpleListFilter):
    title = "وضعیت"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("active", "فعال"), ("out", "خارج شده یا منقضی")]

    def queryset(self, request, queryset):
        live = Q(revoked_at__isnull=True, expires_at__gt=timezone.now())
        if self.value() == "active":
            return queryset.filter(live)
        if self.value() == "out":
            return queryset.exclude(live)
        return queryset


@admin.register(DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device", "state", "created_at", "last_seen_at")
    list_filter = (SessionStateFilter, "platform")
    list_select_related = ("user",)

    @admin.display(description="دستگاه", ordering="device_name")
    def device(self, obj):
        return device_label(obj)

    @admin.display(description="وضعیت")
    def state(self, obj):
        return session_state(obj)
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
