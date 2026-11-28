import io

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import ContentNode

from .models import SectionProgress


class SectionProgressAdminDisplayTests(TestCase):
    def test_long_section_and_book_titles_are_ellipsized_with_hover_text(self):
        call_command("load_samples", stdout=io.StringIO())
        admin_user = User.objects.create_superuser("09120000001", password="Pass-12345")
        book = ContentNode.objects.get(slug="math-1", depth=1)
        chapter = ContentNode.objects.get(slug="limits")
        section = chapter.get_children().first()
        section_title = "عنوان بسیار طولانی برای بخشی از کتاب که باید بدون اسکرول افقی کوتاه نمایش داده شود"
        book_title = "نام بسیار طولانی کتاب آموزشی که در جدول پیشرفت باید بریده نمایش داده شود"
        section.title = section_title
        section.save(update_fields=["title"])
        book.title = book_title
        book.save(update_fields=["title"])
        SectionProgress.objects.create(user=admin_user, node=section, book=book, percent=100, is_done=True)

        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:study_sectionprogress_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="lp-progress-title"')
        self.assertContains(response, f'title="{section_title}"')
        self.assertContains(response, f'title="{book_title}"')
