from django.contrib import admin

from .models import Entitlement, Order, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("title", "scope", "months", "price", "is_active", "order")
    list_editable = ("price", "is_active", "order")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders are a financial record: viewable, never edited or deleted here."""

    list_display = ("id", "user", "title", "amount", "status", "ref_number", "created_at", "paid_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__phone", "ref_number", "track_id", "title")
    readonly_fields = [f.name for f in Order._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    """Admins can grant access by hand (e.g. a gift) and revoke it by archiving; nothing is deleted."""

    list_display = ("user", "book", "major", "all_majors", "starts_at", "ends_at", "is_archived", "order")
    list_filter = ("is_archived", "all_majors", "major")
    search_fields = ("user__phone",)
    autocomplete_fields = ("user",)
    raw_id_fields = ("book", "order")
    readonly_fields = ("order", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False
