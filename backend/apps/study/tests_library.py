from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode
from apps.commerce.models import Entitlement

from .models import LibraryBook, SectionProgress


class PersonalLibraryTests(TestCase):
    """Personal shelf actions affect only shelf metadata, never the right to read or study data."""

    def setUp(self):
        self.user = User.objects.create_user("09120001000")
        _, token = DeviceSession.start(self.user, "library-device")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def make_book(self, slug, *, free=False, published=True):
        book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            slug=slug,
            title=f"کتاب {slug}",
            is_published=published,
            is_free=free,
            price=120_000,
        )
        chapter = book.add_child(
            kind=ContentNode.Kind.CHAPTER,
            slug=f"{slug}-chapter",
            title="فصل اول",
            is_published=published,
        )
        section = chapter.add_child(
            kind=ContentNode.Kind.SECTION,
            slug=f"{slug}-section",
            title="بخش اول",
            is_published=published,
        )
        return book, section

    def books_by_slug(self, response):
        return {entry["book"]["slug"]: entry for entry in response.data["books"]}

    def test_bookshelf_lists_only_full_current_access_and_keeps_private_group_books(self):
        free_book, free_section = self.make_book("library-free", free=True)
        paid_book, _ = self.make_book("library-paid")
        unowned_book, _ = self.make_book("library-unowned")
        group_book, _ = self.make_book("library-group", published=False)
        expired_book, _ = self.make_book("library-expired", published=False)
        manager = User.objects.create_superuser("09120001001", password="manager-test-password")
        Entitlement.objects.create(user=self.user, book=paid_book)
        Entitlement.objects.create(user=self.user, book=group_book, granted_by=manager, ends_at=timezone.now() + timedelta(days=10))
        Entitlement.objects.create(user=self.user, book=expired_book, granted_by=manager, ends_at=timezone.now() - timedelta(seconds=1))
        SectionProgress.objects.create(user=self.user, book=free_book, node=free_section, percent=20)

        response = self.client.get("/api/v1/me/library/")
        self.assertEqual(response.status_code, 200)
        books = self.books_by_slug(response)
        self.assertEqual(set(books), {"library-free", "library-paid", "library-group"})
        self.assertEqual(books["library-free"]["status"], LibraryBook.Status.READING)
        self.assertEqual(books["library-group"]["status"], LibraryBook.Status.LATER)
        self.assertNotIn(unowned_book.slug, books)
        self.assertNotIn(expired_book.slug, books)

    def test_hiding_and_restoring_never_changes_entitlement_or_progress(self):
        book, section = self.make_book("library-purchased")
        entitlement = Entitlement.objects.create(user=self.user, book=book)
        progress = SectionProgress.objects.create(user=self.user, book=book, node=section, percent=55)
        self.assertTrue(AccessMap(self.user, section).readable(section.id))
        before = self.client.get("/api/v1/me/library/").data
        self.assertIn(book.slug, [row["book_slug"] for row in before["reading"]])

        url = f"/api/v1/me/library/books/{book.pk}/"
        hidden = self.client.patch(url, {"hidden": True}, format="json")
        self.assertEqual(hidden.status_code, 200, hidden.data)
        self.assertTrue(hidden.data["hidden"])
        library = self.client.get("/api/v1/me/library/").data
        hidden_item = next(row for row in library["books"] if row["book_id"] == book.pk)
        self.assertTrue(hidden_item["hidden"])
        self.assertNotIn(book.slug, [row["book_slug"] for row in library["reading"]])
        self.assertTrue(Entitlement.objects.filter(pk=entitlement.pk, is_archived=False).exists())
        self.assertTrue(SectionProgress.objects.filter(pk=progress.pk).exists())
        self.assertTrue(AccessMap(self.user, section).readable(section.id))

        restored = self.client.patch(url, {"hidden": False, "status": "finished"}, format="json")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertFalse(restored.data["hidden"])
        library = self.client.get("/api/v1/me/library/").data
        item = next(row for row in library["books"] if row["book_id"] == book.pk)
        self.assertEqual(item["status"], LibraryBook.Status.FINISHED)
        self.assertFalse(item["hidden"])
        self.assertIn(book.slug, [row["book_slug"] for row in library["reading"]])

    def test_expired_group_access_hides_saved_shelf_state_without_deleting_it(self):
        manager = User.objects.create_superuser("09120001002", password="manager-test-password")
        book, section = self.make_book("library-expire-later")
        entitlement = Entitlement.objects.create(
            user=self.user, book=book, granted_by=manager, ends_at=timezone.now() + timedelta(days=1)
        )
        SectionProgress.objects.create(user=self.user, book=book, node=section, percent=60)
        active = self.client.get("/api/v1/me/library/")
        self.assertIn(book.slug, self.books_by_slug(active))
        self.assertIn(book.slug, [row["book_slug"] for row in active.data["reading"]])
        state = LibraryBook.objects.create(user=self.user, book=book, status=LibraryBook.Status.FINISHED)
        Entitlement.objects.filter(pk=entitlement.pk).update(ends_at=timezone.now() - timedelta(seconds=1))

        response = self.client.get("/api/v1/me/library/")
        self.assertNotIn(book.slug, self.books_by_slug(response))
        self.assertNotIn(book.slug, [row["book_slug"] for row in response.data["reading"]])
        self.assertEqual(self.client.patch(f"/api/v1/me/library/books/{book.pk}/", {"hidden": False}, format="json").status_code, 404)
        self.assertTrue(LibraryBook.objects.filter(pk=state.pk, is_hidden=False, status=LibraryBook.Status.FINISHED).exists())

    def test_only_the_learner_with_access_can_change_a_book_shelf(self):
        book, _ = self.make_book("library-owner-only")
        other = User.objects.create_user("09120001003")
        _, token = DeviceSession.start(other, "other-device")
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = other_client.patch(f"/api/v1/me/library/books/{book.pk}/", {"hidden": True}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LibraryBook.objects.filter(user=other, book=book).exists())
        self.assertEqual(APIClient().get("/api/v1/me/library/").status_code, 401)

    def test_personal_order_is_persisted_and_stale_or_partial_orders_are_rejected(self):
        first, _ = self.make_book("library-order-a", free=True)
        second, _ = self.make_book("library-order-b", free=True)
        for book in (first, second):
            response = self.client.patch(
                f"/api/v1/me/library/books/{book.pk}/", {"status": "finished"}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.data)
        ids = [second.pk, first.pk]
        response = self.client.patch(
            "/api/v1/me/library/reorder/", {"status": "finished", "book_ids": ids}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        items = [item for item in self.client.get("/api/v1/me/library/").data["books"] if item["status"] == "finished"]
        self.assertEqual([item["book_id"] for item in items], ids)
        self.assertEqual([item["position"] for item in items], [0, 1])

        stale = self.client.patch(
            "/api/v1/me/library/reorder/", {"status": "finished", "book_ids": [first.pk]}, format="json"
        )
        self.assertEqual(stale.status_code, 409)
        duplicate = self.client.patch(
            "/api/v1/me/library/reorder/", {"status": "finished", "book_ids": [first.pk, first.pk]}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400)
