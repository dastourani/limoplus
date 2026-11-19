from datetime import timedelta

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.jalali import jalali_date, jalali_datetime
from apps.catalog.models import Banner, ContentNode
from apps.catalog.panel_display import badges, fa_number

from .models import Entitlement, Order, Plan, SaleCampaign


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

    list_display = ("owner", "scope", "left", "came_from", "start")
    list_filter = (EntitlementStateFilter, EntitlementKindFilter)
    search_fields = ("user__phone", "book__title")
    list_select_related = ("user", "book", "major", "order", "granted_by")
    autocomplete_fields = ("user",)
    raw_id_fields = ("book", "order")
    readonly_fields = ("order", "granted_by", "created_at")

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

    def save_model(self, request, obj, form, change):
        if not change and obj.book_id and not obj.order_id and not obj.granted_by_id:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False
