from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.contrib.admin.sites import NotRegistered
from django.db.models import Count, Q
from django.utils import timezone

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
    if not session.is_active:  # unused for SESSION_IDLE: signed out by itself
        return badges(("بی‌استفاده، خارج شد", "grey"))
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


class DeviceSwitchFilter(admin.SimpleListFilter):
    title = "دستگاه"
    parameter_name = "devices"

    def lookups(self, request, model_admin):
        return [("many", "تعویض زیاد دستگاه در ۷ روز")]

    def queryset(self, request, queryset):
        if self.value() != "many":
            return queryset
        since = timezone.now() - timedelta(days=7)
        heavy = (DeviceSession.objects.filter(created_at__gte=since).order_by().values("user")
                 .annotate(n=Count("pk")).filter(n__gt=settings.DEVICE_SWITCH_ALERT).values("user"))
        return queryset.filter(pk__in=heavy)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """The list shows at a glance who buys and who studies; a user's page starts with «خلاصه»: access, orders and
    study, each with a link to its full list. Every number here is counted by the database with the list itself."""

    ordering = ("-date_joined",)
    list_display = ("who", "dates", "access", "paid", "study_month")
    list_display_links = ("who",)
    search_fields = ("phone", "email", "first_name", "last_name", "admin_note")
    list_filter = (BoughtFilter, ActiveWeekFilter, DeviceSwitchFilter, "date_joined", "is_active", "can_copy", "can_report", "is_staff")
    readonly_fields = ("overview",)
    fieldsets = (
        ("خلاصه", {"fields": ("overview",)}),
        (None, {"fields": ("phone",)}),
        ("مشخصات", {"fields": ("first_name", "last_name", "email")}),
        ("محدودیت‌ها و وضعیت حساب", {"fields": ("is_active", "can_copy", "can_report", "admin_note")}),
        ("دسترسی به پنل مدیریت", {"fields": ("is_staff", "is_superuser")}),
        ("گذرواژه‌ی پنل، گروه‌ها و اجازه‌های جزئی", {"classes": ("collapse",), "fields": ("password", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"classes": ("collapse",), "fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),)
    inlines = [DeviceSessionInline]

    def has_add_permission(self, request):
        # Creating accounts and granting panel status happen only through the manager-approved onboarding flow.
        return bool(request.user.is_superuser)

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser:
            return self.add_fieldsets if obj is None else self.fieldsets
        return (
            ("خلاصه", {"fields": ("overview",)}),
            (None, {"fields": ("phone",)}),
            ("مشخصات", {"fields": ("first_name", "last_name", "email")}),
            ("محدودیت‌ها و وضعیت حساب", {"fields": ("is_active", "can_copy", "can_report", "admin_note")}),
            ("تاریخ‌ها", {"classes": ("collapse",), "fields": ("last_login", "date_joined")}),
        )

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return self.readonly_fields
        return tuple(dict.fromkeys((*self.readonly_fields, "phone", "first_name", "last_name", "email", "is_active",
                                    "can_copy", "can_report", "admin_note", "last_login", "date_joined")))

    def has_delete_permission(self, request, obj=None):
        # A learner's purchases, progress and notes must never be lost: «فعال» off signs them out instead.
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and object_id and "_quick_action" in request.POST:
            from django.contrib import messages
            from django.shortcuts import redirect

            obj = User.objects.filter(pk=object_id).first()
            if obj and self.has_change_permission(request, obj):
                act = request.POST["_quick_action"]
                if act == "toggle_copy":
                    obj.can_copy = not obj.can_copy
                    obj.save(update_fields=["can_copy"])
                    messages.success(request, "امکان کپی متن برای این کاربر باز شد." if obj.can_copy else "امکان کپی متن برای این کاربر بسته شد.")
                elif act == "toggle_report":
                    obj.can_report = not obj.can_report
                    obj.save(update_fields=["can_report"])
                    messages.success(request, "امکان ارسال گزارش برای این کاربر باز شد." if obj.can_report else "امکان ارسال گزارش برای این کاربر بسته شد.")
                elif act == "revoke_sessions":
                    for s in DeviceSession.active_for(obj):
                        s.revoke()
                    messages.success(request, "کاربر از همه‌ی دستگاه‌های فعال خارج شد.")
                elif act == "toggle_active":
                    obj.is_active = not obj.is_active
                    obj.save(update_fields=["is_active"])
                    if not obj.is_active:
                        for s in DeviceSession.active_for(obj):
                            s.revoke()
                    messages.success(request, "حساب کاربر دوباره فعال شد." if obj.is_active else "حساب کاربر مسدود شد و از همه‌ی دستگاه‌ها خارج گردید.")
                return redirect(request.path)
        return super().changeform_view(request, object_id, form_url, extra_context)

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
            # Signing in on many devices in a week: often one account shared by several people.
            new_devices=Coalesce(one(DeviceSession.objects.filter(created_at__gte=now - timedelta(days=7), **mine), Count("pk")), 0),
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

        many = getattr(obj, "new_devices", 0) > settings.DEVICE_SWITCH_ALERT
        shown = badges(
            obj.is_superuser and ("مدیر کل", "yellow"),
            obj.is_staff and not obj.is_superuser and ("مدیر", "yellow"),
            not obj.is_active and ("غیرفعال", "grey"),
            not obj.can_copy and ("کپی بسته", "red"),
            not obj.can_report and ("گزارش بسته", "red"),
            many and ("تعویض زیاد دستگاه", "red"),
        )
        return "" if shown == "—" else shown

    def get_urls(self):
        urls = super().get_urls()
        from django.urls import path
        custom_urls = [
            path("change-email/", self.admin_site.admin_view(self.change_email_view), name="accounts_user_change_email"),
            path("send-verification/", self.admin_site.admin_view(self.send_verification_view), name="accounts_user_send_verification"),
        ]
        return custom_urls + urls

    def change_email_view(self, request):
        from django.contrib import messages
        from django.core.mail import send_mail
        from django.shortcuts import redirect, render

        user = request.user
        if request.method == "POST":
            new_email = request.POST.get("email", "").strip().lower()
            if not new_email or "@" not in new_email:
                messages.error(request, "ایمیل واردشده معتبر نیست.")
            else:
                user.email = new_email
                user.email_verified_at = None
                token = user.generate_email_verification_token()
                user.save(update_fields=["email"])

                verify_url = request.build_absolute_uri(f"/verify-email/{token}/")
                subject = "تأیید ایمیل در پنل لیموخوان"
                body = (
                    f"استاد گرامی سلام،\n\n"
                    f"برای تأیید ایمیل خود و فعال‌سازی امکان دریافت خروجی‌های کتاب (TeX و ZIP)، لطفاً روی پیوند زیر کلیک کنید:\n"
                    f"{verify_url}\n\n"
                    f"با احترام،\nتیم لیموخوان"
                )
                try:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [new_email], fail_silently=False)
                    messages.success(request, f"ایمیل شما ثبت شد و پیوند تأیید به {new_email} ارسال گردید. لطفاً ایمیل خود را بررسی کنید.")
                except Exception as exc:
                    messages.warning(request, f"ایمیل ثبت شد اما ارسال پیوند با خطا مواجه شد: {exc}")

                return redirect(f"/{settings.ADMIN_URL}")

        context = {
            **self.admin_site.each_context(request),
            "title": "ثبت یا ویرایش ایمیل کاری",
            "user_email": user.email,
            "is_verified": user.is_email_verified,
        }
        return render(request, "admin/accounts/change_email.html", context)

    def send_verification_view(self, request):
        from django.contrib import messages
        from django.core.mail import send_mail
        from django.shortcuts import redirect

        user = request.user
        if not user.email:
            messages.error(request, "ابتدا ایمیل خود را ثبت کنید.")
            return redirect(f"/{settings.ADMIN_URL}")

        token = user.generate_email_verification_token()
        verify_url = request.build_absolute_uri(f"/verify-email/{token}/")
        subject = "تأیید ایمیل در پنل لیموخوان"
        body = (
            f"استاد گرامی سلام،\n\n"
            f"برای تأیید ایمیل خود و فعال‌سازی امکان دریافت خروجی‌های کتاب (TeX و ZIP)، لطفاً روی پیوند زیر کلیک کنید:\n"
            f"{verify_url}\n\n"
            f"با احترام،\nتیم لیموخوان"
        )
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            messages.success(request, f"پیوند تأیید مجدداً به {user.email} ارسال شد.")
        except Exception as exc:
            messages.error(request, f"خطا در ارسال ایمیل: {exc}")

        return redirect(f"/{settings.ADMIN_URL}")

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
        now = timezone.now()
        live = Q(revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gt=now - settings.SESSION_IDLE)
        if self.value() == "active":
            return queryset.filter(live)
        if self.value() == "out":
            return queryset.exclude(live)
        return queryset


@admin.register(DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    change_list_template = "admin/accounts/devicesession/change_list.html"
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
    actions = ["revoke_sessions", "purge_expired_sessions"]

    @admin.action(description="خارج کردن نشست‌های انتخاب‌شده")
    def revoke_sessions(self, request, queryset):
        for session in queryset:
            session.revoke()

    @admin.action(description="پاک کردن نشست‌های خارج‌شده و منقضی قدیمی (بیش از ۷ روز)")
    def purge_expired_sessions(self, request, queryset):
        now = timezone.now()
        live = Q(revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gt=now - settings.SESSION_IDLE)
        cutoff = now - timedelta(days=7)
        deleted, _ = DeviceSession.objects.exclude(live).filter(created_at__lt=cutoff).delete()
        self.message_user(request, f"{deleted} نشست قدیمی پاک شد.")

    def changelist_view(self, request, extra_context=None):
        from apps.catalog.panel_display import fa_number

        now = timezone.now()
        live_q = Q(revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gt=now - settings.SESSION_IDLE)
        live = DeviceSession.objects.filter(live_q)
        ctx = {
            **(extra_context or {}),
            "active_total": fa_number(live.count()),
            "active_android": fa_number(live.filter(platform="android").count()),
            "active_web": fa_number(live.exclude(platform="android").count()),
            "active_users": fa_number(live.values("user_id").distinct().count()),
            "only_active": request.GET.get("state") == "active",
        }
        return super().changelist_view(request, extra_context=ctx)

    def has_add_permission(self, request):
        return False


# Group membership is an approval boundary: only the manager may grant or edit it.
from . import admin_groups as _protected_group_admin  # noqa: E402,F401
