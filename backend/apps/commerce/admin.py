from datetime import timedelta

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.jalali import jalali_date, jalali_datetime
from apps.catalog.models import Banner, ContentNode
from apps.catalog.panel_display import badges, fa_number

from .models import (
    BookAuthorShare,
    BookRoyaltyRule,
    Entitlement,
    Order,
    OrderAuthorRevenue,
    OrderRevenueSnapshot,
    PayoutRequest,
    Plan,
    RevenuePlan,
    SaleCampaign,
    TeacherBankAccount,
    TeacherWallet,
    WalletTransaction,
)


def user_cell(user):
    """Phone, with the name under it when there is one; links to the user's page."""
    url = reverse("admin:accounts_user_change", args=[user.pk])
    name = user.full_name
    return format_html('<a href="{}">{}</a>{}', url, user.phone,
                       format_html('<div class="lp-quiet">{}</div>', name) if name else "")


def toman(amount):
    return format_html('<span style="white-space:nowrap">{} تومان</span>', fa_number(amount)) if amount is not None else "—"


def when(value, with_time=True):
    if not value:
        return "—"
    return format_html('<span style="white-space:nowrap">{}</span>', jalali_datetime(value) if with_time else jalali_date(value))


def entitlement_scope(obj) -> str:
    if obj.book_id:
        return obj.book.title
    if obj.major_id:
        return f"اشتراک رشته‌ی {obj.major}"
    return "اشتراک همه‌ی کتاب‌ها"


def entitlement_left(obj, now=None):
    """A coloured badge: «۱۲ روز» (yellow from seven days down), «همیشگی», «تمام شده», «لغو شده», or a future start."""
    if obj.is_archived:
        return badges(("لغو شده", "grey"))
    now = now or timezone.now()
    if obj.starts_at and obj.starts_at > now:
        return badges((f"از {jalali_date(obj.starts_at)}", "blue"))
    if obj.ends_at is None:
        return badges(("همیشگی", "green"))
    if obj.ends_at <= now:
        return format_html('{}<div class="lp-quiet">{}</div>', badges(("تمام شده", "red")), jalali_date(obj.ends_at))
    rest = obj.ends_at - now
    days = rest.days + (1 if rest.seconds else 0)
    color = "yellow" if days <= 7 else "green"
    return format_html('{}<div class="lp-quiet">تا {}</div>', badges((f"{fa_number(days)} روز", color)), jalali_date(obj.ends_at))


def entitlement_source(obj):
    if obj.order_id:
        url = reverse("admin:commerce_order_change", args=[obj.order_id])
        return format_html('<a href="{}">خرید ({})</a>', url, toman(obj.order.amount))
    if obj.granted_by_id:
        return f"هدیه از {obj.granted_by.full_name or obj.granted_by.phone}"
    return "دستی"


class OrderBookFilter(admin.SimpleListFilter):
    lp_list = True
    title = "کتاب"
    parameter_name = "book_id"

    def lookups(self, request, model_admin):
        from apps.catalog.filters import _book_choices

        return _book_choices(user=request.user)

    def queryset(self, request, queryset):
        return queryset.filter(book_id=self.value()) if self.value() else queryset


class OrderPlanFilter(admin.SimpleListFilter):
    lp_list = True
    title = "طرح اشتراک"
    parameter_name = "plan_id"

    def lookups(self, request, model_admin):
        return [(str(p.pk), f"{p.title} ({fa_number(p.months)} ماهه)") for p in Plan.objects.order_by("order", "price")]

    def queryset(self, request, queryset):
        return queryset.filter(plan_id=self.value()) if self.value() else queryset


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("title", "scope", "months", "price", "is_active", "order")
    list_editable = ("price", "is_active", "order")
    search_fields = ("title",)

    # Subscription prices are financial settings, not teacher/editor controls.
    def has_module_permission(self, request):
        return bool(request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        # New plans cover all books; an old one-major plan keeps its value (shown, not editable) and is no longer sold.
        return ("scope",) if obj is not None else ()

    def get_exclude(self, request, obj=None):
        return ("scope",) if obj is None else ()


class CampaignBannerForm(forms.ModelForm):
    """A sale campaign always has one sale-style banner; its destination and timer are derived, not hand-copied."""

    class Meta:
        model = Banner
        fields = ("template", "title", "subtitle", "button", "image", "audience_book", "priority", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["template"] = Banner.Template.SALE
        self.fields["template"].widget = forms.HiddenInput()
        self.fields["priority"].initial = 100
        self.fields["title"].help_text = "این بنر خودکار قیمت و مهلت همین کمپین را می‌گیرد؛ لازم نیست قیمت را دستی در متن بنویسید."

    def clean_template(self):
        return Banner.Template.SALE


class CampaignBannerInline(admin.StackedInline):
    model = Banner
    form = CampaignBannerForm
    fk_name = "sale_campaign"
    extra = 1
    min_num = 1
    max_num = 1
    validate_min = True
    can_delete = False
    verbose_name = "بنر همین کمپین (اپ و وب‌سایت)"
    verbose_name_plural = "بنر همین کمپین (اپ و وب‌سایت)"


@admin.register(SaleCampaign)
class SaleCampaignAdmin(admin.ModelAdmin):
    """A timed price and its matching app/site banner are one superuser-managed campaign."""

    list_display = ("title", "product", "regular_price", "discounted_price_display", "discount", "state", "is_active")
    list_filter = ("is_active", "starts_at", "ends_at")
    search_fields = ("title", "book__title", "plan__title")
    autocomplete_fields = ()
    readonly_fields = ("created_at", "updated_at")
    fields = ("title", "book", "plan", "discounted_price", "starts_at", "ends_at", "is_active", "created_at", "updated_at")
    inlines = (CampaignBannerInline,)

    def has_module_permission(self, request):
        return bool(request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        # Campaigns are historical financial configuration; turn them off instead of deleting.
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("book", "plan")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "book" and field is not None:
            from .pricing import campaign_book_queryset

            eligible = campaign_book_queryset(field.queryset)
            # Keep a legacy/current choice editable so a manager can turn its campaign off; it is never offered
            # when creating a campaign, and model validation prevents an ineligible campaign remaining active.
            object_id = getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("object_id")
            current = self.get_queryset(request).filter(pk=object_id).values_list("book_id", flat=True).first() if object_id else None
            if current:
                eligible = eligible | field.queryset.filter(pk=current)
            field.queryset = eligible
        return field

    @admin.display(description="محصول")
    def product(self, obj):
        return obj.book.title if obj.book_id else (obj.plan.title if obj.plan_id else "—")

    @admin.display(description="قیمت عادی")
    def regular_price(self, obj):
        return toman(obj.regular_price)

    @admin.display(description="قیمت ویژه", ordering="discounted_price")
    def discounted_price_display(self, obj):
        return toman(obj.discounted_price)

    @admin.display(description="میزان تخفیف")
    def discount(self, obj):
        if not obj.regular_price or not obj.discounted_price or obj.discounted_price >= obj.regular_price:
            return badges(("قیمت پایه تغییر کرده", "red"))
        return toman(obj.regular_price - obj.discounted_price)

    @admin.display(description="وضعیت")
    def state(self, obj):
        now = timezone.now()
        if not obj.is_active:
            return badges(("غیرفعال", "grey"))
        if obj.starts_at > now:
            return badges((f"شروع {jalali_date(obj.starts_at)}", "blue"))
        if obj.ends_at <= now:
            return badges(("تمام‌شده", "red"))
        return badges((f"تا {jalali_date(obj.ends_at)}", "green"))


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders are a financial record: viewable, never edited or deleted here."""

    list_display = ("buyer", "what", "price", "state", "made", "payment")
    list_filter = ("status", "created_at", OrderBookFilter, OrderPlanFilter)
    change_list_template = "admin/commerce/order/change_list.html"

    def get_urls(self):
        from django.urls import path

        site = self.admin_site.admin_view
        return [
            path("report/", site(self.report_view), name="commerce_order_report"),
            path("report/csv/", site(self.report_csv), name="commerce_order_report_csv"),
        ] + super().get_urls()

    def _may_see(self, request):
        from django.core.exceptions import PermissionDenied

        if not self.has_view_permission(request):
            raise PermissionDenied

    def report_view(self, request):
        from django.template.response import TemplateResponse

        from . import report

        self._may_see(request)
        data = report.build(request.GET.get("range", "month"), request.GET.get("from", ""), request.GET.get("to", ""))
        context = {**self.admin_site.each_context(request), "title": "گزارش فروش", "opts": self.model._meta, **data,
                   "from_text": request.GET.get("from", ""), "to_text": request.GET.get("to", ""),
                   "query": request.GET.urlencode()}
        return TemplateResponse(request, "admin/commerce/order/report.html", context)

    def report_csv(self, request):
        from django.http import HttpResponse

        from . import report

        self._may_see(request)
        start, end, _ = report.period(request.GET.get("range", "month"), request.GET.get("from", ""), request.GET.get("to", ""))
        response = HttpResponse(report.csv_file(start, end), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="limookhan-orders-{start:%Y%m%d}-{end:%Y%m%d}.csv"'
        return response

    def changelist_view(self, request, extra_context=None):
        """Above the list: what the shown (filtered) orders add up to, paid ones only."""
        from django.db.models import Count, Sum

        response = super().changelist_view(request, extra_context)
        cl = getattr(response, "context_data", {}).get("cl") if hasattr(response, "context_data") else None
        if cl is not None:
            paid = cl.queryset.filter(status=Order.Status.PAID).aggregate(n=Count("pk"), s=Sum("amount"))
            response.context_data["lp_paid_total"] = {"n": fa_number(paid["n"]), "sum": fa_number(paid["s"] or 0)}
        return response
    search_fields = ("user__phone", "ref_number", "track_id", "title")
    readonly_fields = [f.name for f in Order._meta.fields]
    list_select_related = ("user",)

    @admin.display(description="خریدار", ordering="user__phone")
    def buyer(self, obj):
        return user_cell(obj.user)

    @admin.display(description="شرح", ordering="title")
    def what(self, obj):
        return format_html('<div style="min-width:220px">{}</div>', obj.title)

    @admin.display(description="ایجاد", ordering="created_at")
    def made(self, obj):
        return when(obj.created_at)

    @admin.display(description="مبلغ", ordering="amount")
    def price(self, obj):
        return toman(obj.amount)

    @admin.display(description="وضعیت", ordering="status")
    def state(self, obj):
        color = {Order.Status.PAID: "green", Order.Status.PENDING: "yellow", Order.Status.FAILED: "red"}.get(obj.status, "grey")
        return badges((obj.get_status_display(), color))

    @admin.display(description="پرداخت (زمان و پیگیری)", ordering="paid_at")
    def payment(self, obj):
        if not obj.paid_at:
            return "—"
        ref = format_html('<div class="lp-quiet" dir="ltr" style="text-align:right">{}</div>', obj.ref_number) if obj.ref_number else ""
        return format_html("{}{}", when(obj.paid_at), ref)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntitlementStateFilter(admin.SimpleListFilter):
    title = "وضعیت"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("active", "فعال"), ("soon", "کمتر از ۷ روز مانده"), ("ended", "تمام شده"), ("cancelled", "لغو شده")]

    def queryset(self, request, queryset):
        now = timezone.now()
        v = self.value()
        if v == "active":
            return queryset.filter(pk__in=Entitlement.active_for_any(now).values("pk"))
        if v == "soon":
            return queryset.filter(is_archived=False, starts_at__lte=now, ends_at__gt=now, ends_at__lte=now + timedelta(days=7))
        if v == "ended":
            return queryset.filter(is_archived=False, ends_at__lte=now)
        if v == "cancelled":
            return queryset.filter(is_archived=True)
        return queryset


class EntitlementKindFilter(admin.SimpleListFilter):
    title = "نوع"
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return [("book", "کتاب"), ("sub", "اشتراک"), ("gift", "هدیه‌ی مدیر")]

    def queryset(self, request, queryset):
        v = self.value()
        if v == "book":
            return queryset.filter(book__isnull=False)
        if v == "sub":
            return queryset.filter(book__isnull=True)
        if v == "gift":
            return queryset.filter(order__isnull=True, granted_by__isnull=False)
        return queryset


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    """Admins can grant access by hand and revoke it by archiving; nothing is deleted. A book given by hand here is a
    gift from the admin who saves it (the book page's «هدیه به کاربر» is the easier way)."""

    list_display = ("owner", "scope", "left", "came_from", "start", "warning_sent")
    list_filter = (EntitlementStateFilter, EntitlementKindFilter)
    search_fields = ("user__phone", "book__title")
    list_select_related = ("user", "book", "major", "order", "granted_by")
    autocomplete_fields = ("user",)
    raw_id_fields = ("book", "order")
    readonly_fields = ("order", "granted_by", "created_at", "expiry_warning_sent_at")

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="کاربر", ordering="user__phone")
    def owner(self, obj):
        return user_cell(obj.user)

    @admin.display(description="شروع", ordering="starts_at")
    def start(self, obj):
        return when(obj.starts_at, with_time=False)

    @admin.display(description="دامنه")
    def scope(self, obj):
        return entitlement_scope(obj)

    @admin.display(description="مانده", ordering="ends_at")
    def left(self, obj):
        return entitlement_left(obj)

    @admin.display(description="از کجا")
    def came_from(self, obj):
        return entitlement_source(obj)

    @admin.display(description="هشدار انقضا", ordering="expiry_warning_sent_at")
    def warning_sent(self, obj):
        if not obj.expiry_warning_sent_at:
            return "—"
        return when(obj.expiry_warning_sent_at, with_time=True)

    def save_model(self, request, obj, form, change):
        if not change and obj.book_id and not obj.order_id and not obj.granted_by_id:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RevenuePlan)
class RevenuePlanAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "author_share_display", "platform_share_display", "sales_cap_display", "date_window", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("title", "code", "description")
    fieldsets = (
        ("مشخصات طرح", {"fields": ("title", "code", "description", "is_active", "is_default")}),
        ("درصد تسهیم", {"fields": ("author_share_percent", "platform_share_percent")}),
        ("محدودیت‌ها و سقف‌ها", {"fields": ("max_sales_count", "starts_at", "ends_at")}),
    )

    def has_module_permission(self, request):
        return bool(request.user.is_superuser)

    @admin.display(description="سهم مؤلفان")
    def author_share_display(self, obj):
        return f"{obj.author_share_percent}٪"

    @admin.display(description="سهم پلتفرم")
    def platform_share_display(self, obj):
        return f"{obj.platform_share_percent}٪"

    @admin.display(description="سقف فروش")
    def sales_cap_display(self, obj):
        return f"{fa_number(obj.max_sales_count)} نسخه" if obj.max_sales_count else "نامحدود"

    @admin.display(description="بازه زمانی")
    def date_window(self, obj):
        if not obj.starts_at and not obj.ends_at:
            return "دائمی"
        s = jalali_date(obj.starts_at) if obj.starts_at else "شروع"
        e = jalali_date(obj.ends_at) if obj.ends_at else "پایان نامحدود"
        return f"{s} تا {e}"


class BookAuthorShareInline(admin.TabularInline):
    model = BookAuthorShare
    extra = 1
    raw_id_fields = ["author"]
    fields = ("author", "share_percent", "role_title", "is_active")


@admin.register(BookRoyaltyRule)
class BookRoyaltyRuleAdmin(admin.ModelAdmin):
    list_display = ("book_title", "plan_applied", "split_summary", "authors_count", "updated_at_display")
    list_filter = ("revenue_plan", "is_custom_split")
    search_fields = ("book__title", "notes")
    raw_id_fields = ["book"]
    inlines = [BookAuthorShareInline]
    fieldsets = (
        ("کتاب و طرح", {"fields": ("book", "revenue_plan", "notes")}),
        ("تنظیمات سفارشی (Override)", {
            "fields": ("is_custom_split", "custom_platform_share_percent"),
            "description": "اگر مایلید بدون استفاده از طرح‌ها، مستقیماً درصد پلتفرم برای این کتاب مشخص شود.",
        }),
    )

    def has_module_permission(self, request):
        return bool(request.user.is_superuser)

    @admin.display(description="کتاب")
    def book_title(self, obj):
        return obj.book.title

    @admin.display(description="طرح اعمال‌شده")
    def plan_applied(self, obj):
        if obj.is_custom_split:
            return badges(("درصد سفارشی", "yellow"))
        if obj.revenue_plan:
            return obj.revenue_plan.title
        return badges(("طرح پیش‌فرض سامانه", "blue"))

    @admin.display(description="خلاصه تسهیم")
    def split_summary(self, obj):
        if obj.is_custom_split and obj.custom_platform_share_percent is not None:
            p = obj.custom_platform_share_percent
            return f"پلتفرم {p}٪ / مؤلفان {100 - p}٪"
        if obj.revenue_plan:
            return f"پلتفرم {obj.revenue_plan.platform_share_percent}٪ / مؤلفان {obj.revenue_plan.author_share_percent}٪"
        return "طرح عمومی"

    @admin.display(description="تعداد مؤلفان")
    def authors_count(self, obj):
        c = obj.author_shares.count()
        return fa_number(c) if c else "پیش‌فرض استادان کتاب"

    @admin.display(description="آخرین تغییر")
    def updated_at_display(self, obj):
        return jalali_date(obj.updated_at)


class OrderAuthorRevenueInline(admin.TabularInline):
    model = OrderAuthorRevenue
    extra = 0
    can_delete = False
    readonly_fields = ("author", "share_percent", "amount", "is_settled", "settled_at", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OrderRevenueSnapshot)
class OrderRevenueSnapshotAdmin(admin.ModelAdmin):
    list_display = ("order_link", "book_link", "total_toman", "platform_toman", "authors_toman", "plan_name", "created_display")
    list_filter = ("revenue_plan",)
    search_fields = ("order__id", "book__title", "order__user__phone")
    inlines = [OrderAuthorRevenueInline]
    readonly_fields = [f.name for f in OrderRevenueSnapshot._meta.fields]

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("order", "book", "revenue_plan")
        if request.user.is_superuser:
            return qs
        # استاد فقط اسنپ‌شات سفارشاتی را می‌بیند که در آن سهم دارد
        return qs.filter(author_revenues__author=request.user).distinct()

    @admin.display(description="سفارش")
    def order_link(self, obj):
        return f"سفارش #{obj.order_id}"

    @admin.display(description="کتاب")
    def book_link(self, obj):
        return obj.book.title if obj.book else "—"

    @admin.display(description="مبلغ کل")
    def total_toman(self, obj):
        return toman(obj.total_amount)

    @admin.display(description="سهم پلتفرم")
    def platform_toman(self, obj):
        return toman(obj.platform_share_amount)

    @admin.display(description="جمع سهم مؤلفان")
    def authors_toman(self, obj):
        return toman(obj.total_authors_amount)

    @admin.display(description="زمان ثبت")
    def created_display(self, obj):
        return jalali_datetime(obj.created_at)


@admin.register(OrderAuthorRevenue)
class OrderAuthorRevenueAdmin(admin.ModelAdmin):
    list_display = ("order_number", "book_name", "author_user", "share_pct", "amount_toman", "status_chip", "available_date", "created_time")
    list_filter = ("release_status", "is_settled")
    search_fields = ("snapshot__order__id", "snapshot__book__title", "author__phone")
    readonly_fields = [f.name for f in OrderAuthorRevenue._meta.fields]

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("snapshot__order", "snapshot__book", "author")
        if request.user.is_superuser:
            return qs
        # استاد فقط رکوردهای سهم خودش را می‌بیند
        return qs.filter(author=request.user)

    @admin.display(description="سفارش")
    def order_number(self, obj):
        return f"سفارش #{obj.snapshot.order_id}"

    @admin.display(description="کتاب")
    def book_name(self, obj):
        return obj.snapshot.book.title if obj.snapshot.book else "—"

    @admin.display(description="مؤلف")
    def author_user(self, obj):
        return user_cell(obj.author)

    @admin.display(description="درصد سهم")
    def share_pct(self, obj):
        return f"{obj.share_percent}٪"

    @admin.display(description="مبلغ سهم استاد")
    def amount_toman(self, obj):
        return toman(obj.amount)

    @admin.display(description="وضعیت دسترسی")
    def status_chip(self, obj):
        if obj.release_status == OrderAuthorRevenue.ReleaseStatus.AVAILABLE:
            color = "green"
        elif obj.release_status == OrderAuthorRevenue.ReleaseStatus.PENDING:
            color = "yellow"
        else:
            color = "red"
        return badges((obj.get_release_status_display(), color))

    @admin.display(description="تاریخ آزادسازی")
    def available_date(self, obj):
        if obj.release_status == OrderAuthorRevenue.ReleaseStatus.AVAILABLE:
            return badges(("آزادشده", "green"))
        if not obj.available_at:
            return "—"
        return jalali_date(obj.available_at)

    @admin.display(description="تاریخ خرید")
    def created_time(self, obj):
        return jalali_datetime(obj.created_at)


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "amount", "available_balance_after", "pending_balance_after", "debt_balance_after", "description", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TeacherWallet)
class TeacherWalletAdmin(admin.ModelAdmin):
    list_display = ("teacher_cell", "available_toman", "locked_toman", "pending_toman", "debt_toman", "net_toman", "total_earned_toman", "health_badge")
    search_fields = ("teacher__phone", "teacher__first_name", "teacher__last_name")
    inlines = [WalletTransactionInline]
    readonly_fields = ("teacher", "pending_balance", "available_balance", "locked_balance", "debt_balance", "total_earned", "total_withdrawn", "created_at", "updated_at")

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_view_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        if request.user.is_superuser:
            return True
        if not is_book_teacher(request.user):
            return False
        return obj is None or obj.teacher_id == request.user.id

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("teacher")
        if request.user.is_superuser:
            return qs
        return qs.filter(teacher=request.user)

    @admin.display(description="استاد")
    def teacher_cell(self, obj):
        return user_cell(obj.teacher)

    @admin.display(description="موجودی قابل برداشت")
    def available_toman(self, obj):
        return toman(obj.available_balance)

    @admin.display(description="مسدود جهت تسویه")
    def locked_toman(self, obj):
        return toman(obj.locked_balance) if obj.locked_balance > 0 else "۰ تومان"

    @admin.display(description="در انتظار گارانتی")
    def pending_toman(self, obj):
        return toman(obj.pending_balance)

    @admin.display(description="بدهی معوق (استرداد)")
    def debt_toman(self, obj):
        return toman(obj.debt_balance) if obj.debt_balance > 0 else "۰ تومان"

    @admin.display(description="خالص قابل تسویه")
    def net_toman(self, obj):
        return toman(obj.net_withdrawable_amount)

    @admin.display(description="کل درآمد")
    def total_earned_toman(self, obj):
        return toman(obj.total_earned)

    @admin.display(description="سلامت تراز")
    def health_badge(self, obj):
        from .wallet import audit_teacher_wallet
        res = audit_teacher_wallet(obj)
        if res["is_healthy"]:
            return badges(("تراز سالم و منطبق", "green"))
        return badges(("دارای مغایرت", "red"))


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("teacher_cell", "event_title", "amount_toman", "available_after", "pending_after", "order_ref", "created_display")
    list_filter = ("event_type",)
    search_fields = ("wallet__teacher__phone", "description", "idempotency_key")
    readonly_fields = [f.name for f in WalletTransaction._meta.fields]

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_view_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        if request.user.is_superuser:
            return True
        if not is_book_teacher(request.user):
            return False
        return obj is None or obj.wallet.teacher_id == request.user.id

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("wallet__teacher", "reference_order")
        if request.user.is_superuser:
            return qs
        return qs.filter(wallet__teacher=request.user)

    @admin.display(description="استاد")
    def teacher_cell(self, obj):
        return user_cell(obj.wallet.teacher)

    @admin.display(description="نوع رویداد")
    def event_title(self, obj):
        color_map = {
            WalletTransaction.EventType.RELEASE_AVAILABLE: "green",
            WalletTransaction.EventType.EARN_PENDING: "yellow",
            WalletTransaction.EventType.REFUND_ADJUSTMENT: "red",
            WalletTransaction.EventType.WITHDRAW_PAID: "blue",
            WalletTransaction.EventType.WITHDRAW_HOLD: "grey",
        }
        return badges((obj.get_event_type_display(), color_map.get(obj.event_type, "grey")))

    @admin.display(description="مبلغ")
    def amount_toman(self, obj):
        return toman(obj.amount)

    @admin.display(description="مانده قابل برداشت")
    def available_after(self, obj):
        return toman(obj.available_balance_after)

    @admin.display(description="مانده در انتظار")
    def pending_after(self, obj):
        return toman(obj.pending_balance_after)

    @admin.display(description="سفارش")
    def order_ref(self, obj):
        return f"سفارش #{obj.reference_order_id}" if obj.reference_order_id else "—"

    @admin.display(description="زمان")
    def created_display(self, obj):
        return jalali_datetime(obj.created_at)


@admin.register(TeacherBankAccount)
class TeacherBankAccountAdmin(admin.ModelAdmin):
    list_display = ("teacher_cell", "account_holder_name", "iban", "bank_name", "verification_badge", "updated_display")
    list_filter = ("is_verified",)
    search_fields = ("teacher__phone", "account_holder_name", "iban", "bank_name")

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_view_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        if request.user.is_superuser:
            return True
        if not is_book_teacher(request.user):
            return False
        return obj is None or obj.teacher_id == request.user.id

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        from apps.catalog.access import is_book_teacher
        if not is_book_teacher(request.user):
            return False
        return obj is None or obj.teacher_id == request.user.id

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("teacher")
        if request.user.is_superuser:
            return qs
        return qs.filter(teacher=request.user)

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ("created_at", "updated_at")
        # استاد نمی‌تواند خودش شبای خود را تایید کند
        return ("teacher", "is_verified", "notes", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.teacher = request.user
            # هر تغییری توسط استاد، نیازمند تایید مجدد است
            if change and ("iban" in form.changed_data or "account_holder_name" in form.changed_data):
                obj.is_verified = False
        super().save_model(request, obj, form, change)

    @admin.display(description="استاد")
    def teacher_cell(self, obj):
        return user_cell(obj.teacher)

    @admin.display(description="وضعیت تایید شبا")
    def verification_badge(self, obj):
        if obj.is_verified:
            return badges(("تایید شده", "green"))
        return badges(("در انتظار تایید مدیر", "yellow"))

    @admin.display(description="آخرین بروزرسانی")
    def updated_display(self, obj):
        return jalali_date(obj.updated_at)


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = ("payout_id", "teacher_cell", "amount_toman", "account_holder_snapshot", "iban_snapshot", "status_chip", "tracking_code", "created_time")
    list_filter = ("status",)
    search_fields = ("teacher__phone", "account_holder_snapshot", "iban_snapshot", "tracking_code")
    actions = ["export_paya_csv", "mark_as_processing_action"]

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_view_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        if request.user.is_superuser:
            return True
        if not is_book_teacher(request.user):
            return False
        return obj is None or obj.teacher_id == request.user.id

    def has_add_permission(self, request):
        # فقط استاد یا مدیر می‌توانند درخواست اضافه کنند
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_superuser or is_book_teacher(request.user))

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("teacher", "processed_by")
        if request.user.is_superuser:
            return qs
        return qs.filter(teacher=request.user)

    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            return ("status", "account_holder_snapshot", "iban_snapshot", "bank_name_snapshot", "tracking_code", "receipt_note", "rejection_reason", "processed_by", "created_at", "paid_at")
        if obj and obj.status in (PayoutRequest.Status.PAID, PayoutRequest.Status.REJECTED):
            return [f.name for f in PayoutRequest._meta.fields]
        return ("teacher", "amount", "account_holder_snapshot", "iban_snapshot", "bank_name_snapshot", "processed_by", "created_at", "paid_at")

    def save_model(self, request, obj, form, change):
        if not change:
            from .wallet import request_teacher_payout
            teacher = request.user if not request.user.is_superuser else (obj.teacher or request.user)
            payout = request_teacher_payout(teacher=teacher, amount=obj.amount)
            obj.pk = payout.pk
            return

        # تغییر وضعیت توسط مدیر
        if request.user.is_superuser and change:
            orig = PayoutRequest.objects.get(pk=obj.pk)
            if orig.status != obj.status:
                if obj.status == PayoutRequest.Status.PAID:
                    from .wallet import finalize_payout_paid
                    finalize_payout_paid(orig, tracking_code=obj.tracking_code, receipt_note=obj.receipt_note, manager_user=request.user)
                    return
                elif obj.status == PayoutRequest.Status.REJECTED:
                    from .wallet import reject_payout_request
                    reject_payout_request(orig, reason=obj.rejection_reason or "رد درخواست توسط مدیریت", manager_user=request.user)
                    return

        super().save_model(request, obj, form, change)

    @admin.display(description="شناسه")
    def payout_id(self, obj):
        return f"تسویه #{obj.id}"

    @admin.display(description="استاد")
    def teacher_cell(self, obj):
        return user_cell(obj.teacher)

    @admin.display(description="مبلغ درخواستی")
    def amount_toman(self, obj):
        return toman(obj.amount)

    @admin.display(description="وضعیت")
    def status_chip(self, obj):
        color_map = {
            PayoutRequest.Status.PAID: "green",
            PayoutRequest.Status.PENDING: "yellow",
            PayoutRequest.Status.PROCESSING: "blue",
            PayoutRequest.Status.REJECTED: "red",
        }
        return badges((obj.get_status_display(), color_map.get(obj.status, "grey")))

    @admin.display(description="زمان ثبت")
    def created_time(self, obj):
        return jalali_datetime(obj.created_at)

    @admin.action(description="دانلود فایل استاندارد پایا (اکسل/CSV بانک)")
    def export_paya_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="paya_batch_transfer.csv"'

        writer = csv.writer(response)
        writer.writerow(["شناسه تسویه", "نام صاحب حساب", "شماره شبا (IBAN)", "مبلغ (ریال)", "مبلغ (تومان)", "شرح"])

        for p in queryset:
            writer.writerow([
                p.id,
                p.account_holder_snapshot,
                p.iban_snapshot,
                p.amount * 10,
                p.amount,
                f"تسویه حساب حق‌التألیف شماره {p.id}",
            ])
        return response

    @admin.action(description="تغییر وضعیت به در حال واریز بانکی")
    def mark_as_processing_action(self, request, queryset):
        from .wallet import mark_payout_as_processing
        count = 0
        for p in queryset.filter(status=PayoutRequest.Status.PENDING):
            mark_payout_as_processing(p, manager_user=request.user)
            count += 1
        self.message_user(request, f"{count} درخواست تسویه به وضعیت «در حال واریز بانکی» منتقل شدند.")



