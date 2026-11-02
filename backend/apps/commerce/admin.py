from django.contrib import admin

from .models import Entitlement, Order, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("title", "scope", "months", "price", "is_active", "order")
    list_editable = ("price", "is_active", "order")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        # New plans cover all books; an old one-major plan keeps its value but is no longer sold.
        if db_field.name == "scope":
            kwargs["choices"] = [(Plan.Scope.ALL.value, Plan.Scope.ALL.label), (Plan.Scope.MAJOR.value, Plan.Scope.MAJOR.label)]
        return super().formfield_for_choice_field(db_field, request, **kwargs)


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
    """Admins can grant access by hand and revoke it by archiving; nothing is deleted. A book given by hand here is a
    gift from the admin who saves it (the book page's «هدیه به کاربر» is the easier way)."""

    list_display = ("user", "book", "major", "all_majors", "starts_at", "ends_at", "is_archived", "order")
    list_filter = ("is_archived", "all_majors", "major")
    search_fields = ("user__phone",)
    autocomplete_fields = ("user",)
    raw_id_fields = ("book", "order")
    readonly_fields = ("order", "granted_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.book_id and not obj.order_id and not obj.granted_by_id:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False
