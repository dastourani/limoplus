"""Read-only audit of existing non-superuser staff privileges before approving book teachers."""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.catalog.access import BOOK_EDITOR_GROUP


class Command(BaseCommand):
    help = "Read-only audit of non-superuser staff groups, direct permissions and book-editor rows."

    @staticmethod
    def _permission_names(permissions):
        return sorted(f"{p.content_type.app_label}.{p.codename}" for p in permissions)

    def handle(self, *args, **options):
        users = (User.objects.filter(is_staff=True, is_superuser=False)
                 .prefetch_related("groups__permissions__content_type", "user_permissions__content_type", "edited_books__book")
                 .order_by("phone"))
        self.stdout.write(self.style.WARNING("گزارش فقط‌خواندنی؛ هیچ حساب، گروه یا دسترسی‌ای تغییر نمی‌کند."))
        if not users.exists():
            self.stdout.write("هیچ حساب staff غیرسوپریوزری برای بررسی پیدا نشد.")
            return

        for user in users:
            groups = list(user.groups.all())
            group_perms = sorted({
                f"{permission.content_type.app_label}.{permission.codename}"
                for group in groups
                for permission in group.permissions.all()
            })
            editors = [
                f"{row.book.title} (تصمیم انتشار قدیمی={'بله' if row.can_publish else 'خیر'})"
                for row in user.edited_books.select_related("book").order_by("book__title")
            ]
            self.stdout.write("")
            self.stdout.write(f"حساب: {user.phone} | فعال: {'بله' if user.is_active else 'خیر'}")
            self.stdout.write(f"گروه‌ها: {', '.join(g.name for g in groups) or '—'}")
            self.stdout.write(f"عضو گروه استاد کتاب: {'بله' if any(g.name == BOOK_EDITOR_GROUP for g in groups) else 'خیر'}")
            self.stdout.write(f"مجوزهای مستقیم: {', '.join(self._permission_names(user.user_permissions.all())) or '—'}")
            self.stdout.write(f"مجوزهای گروهی: {', '.join(group_perms) or '—'}")
            self.stdout.write(f"ردیف‌های استاد کتاب: {'؛ '.join(editors) or '—'}")
