from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import ContentNode, Major
from apps.commerce.models import Entitlement, Order, Plan
from apps.learning.models import Choice, Question, QuizAnswer
from apps.study.models import ChapterReview, ReviewSession

from .checks import check_offline_health, check_payments_and_entitlements, check_review_sessions, run_all_health_checks, verify_settled_order
from .middleware import RequestDiagnosticsMiddleware
from .models import ErrorEvent, ErrorEventReceipt, ErrorGroup, HealthCheckRun
from .service import build_ai_report, prune_old_events, record_event

User = get_user_model()


class DiagnosticsIngestionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="09121112233", password="pass")
        self.client = APIClient()

    def test_ingest_is_idempotent_on_event_id_and_counts_unique_installs(self):
        payload = {
            "event_id": "evt_retry_same_1",
            "kind": "offline",
            "severity": "error",
            "code": "offline_corrupt",
            "title": "فایل بستهٔ آفلاین خراب است",
            "install_id": "inst_phone_a",
            "platform": "android",
            "channel": "official",
            "app_build": "116",
            "is_offline": True,
            "context": {"book_slug": "math-1", "node_id": 10},
        }
        r1 = self.client.post("/api/v1/diagnostics/events/", payload, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json(), {"accepted": 1, "duplicates": 0})

        # Same event_id resent after dropped network response -> must NOT increment counts.
        r2 = self.client.post("/api/v1/diagnostics/events/", payload, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json(), {"accepted": 0, "duplicates": 1})

        group = ErrorGroup.objects.get(code="offline_corrupt")
        self.assertEqual(group.event_count, 1)
        self.assertEqual(group.install_count, 1)

        # Fresh occurrence on same install increments event_count but keeps install_count=1.
        r3 = self.client.post(
            "/api/v1/diagnostics/events/",
            {**payload, "event_id": "evt_retry_same_2"},
            format="json",
        )
        self.assertEqual(r3.status_code, 200)
        group.refresh_from_db()
        self.assertEqual(group.event_count, 2)
        self.assertEqual(group.install_count, 1)

        # Occurrence from a second install increments both.
        r4 = self.client.post(
            "/api/v1/diagnostics/events/",
            {**payload, "event_id": "evt_other_install_1", "install_id": "inst_phone_b"},
            format="json",
        )
        self.assertEqual(r4.status_code, 200)
        group.refresh_from_db()
        self.assertEqual(group.event_count, 3)
        self.assertEqual(group.install_count, 2)

    def test_200_events_keep_exact_count_and_dedupe_even_after_50_sample_trim(self):
        now = timezone.now()
        for i in range(200):
            _, created = record_event(
                source=ErrorGroup.Source.CLIENT,
                kind=ErrorGroup.Kind.OFFLINE,
                code="offline_corrupt",
                title="فایل بستهٔ آفلاین خراب است",
                event_id=f"evt_bulk_{i}",
                install_id=f"inst_{i % 5}",
                created_at=now,
            )
            self.assertTrue(created)

        group = ErrorGroup.objects.get(code="offline_corrupt")
        self.assertEqual(group.event_count, 200)
        self.assertEqual(group.events.count(), 50)
        self.assertEqual(ErrorEventReceipt.objects.filter(group=group).count(), 200)

        # Re-sending the very first event (already trimmed from ErrorEvent) must NOT increment counts!
        r_dup = self.client.post(
            "/api/v1/diagnostics/events/",
            {
                "event_id": "evt_bulk_0",
                "kind": "offline",
                "code": "offline_corrupt",
                "title": "فایل بستهٔ آفلاین خراب است",
                "install_id": "inst_0",
            },
            format="json",
        )
        self.assertEqual(r_dup.status_code, 200)
        self.assertEqual(r_dup.json(), {"accepted": 0, "duplicates": 1})

        group.refresh_from_db()
        self.assertEqual(group.event_count, 200)
        self.assertEqual(group.events.count(), 50)

        # 24h offline health check must count all 200 events, not just the 50 kept samples.
        off_run = check_offline_health(now=now)
        self.assertEqual(off_run.details["offline_corrupt"], 200)
        self.assertEqual(off_run.issues_found, 200)

    def test_privacy_scrubs_english_text_extra_keys_email_and_persian_from_db_bale_and_ai_report(self):
        bale_messages: list[str] = []
        english_sentence = "The passive voice expresses an action done to the subject"
        extra_note = "یادداشت آزمایشی خصوصی دانش‌آموز"
        with mock.patch("apps.diagnostics.service.notify_bale_after_commit", side_effect=lambda msg, **kw: bale_messages.append(msg)):
            # 1. Server unhandled exception containing English lesson sentence + email + Persian text
            rf = RequestFactory()
            mw = RequestDiagnosticsMiddleware(lambda req: None)
            req = rf.post(
                "/api/v1/search/?q=عبارت",
                HTTP_X_REQUEST_ID="req_priv_srv_1",
                HTTP_X_APP_PLATFORM="web",
                HTTP_X_APP_WEB_COMMIT="sha_priv_99",
            )
            try:
                raise ValueError(f"{english_sentence} student@example.com عبارت خصوصی دانش‌آموز")
            except ValueError as exc:
                mw.process_exception(req, exc)

            # 2. Client error payload containing unquoted English sentence + disallowed extra key
            r_cli = self.client.post(
                "/api/v1/diagnostics/events/",
                {
                    "event_id": "evt_priv_cli_1",
                    "kind": "client_error",
                    "severity": "critical",
                    "code": "js_error",
                    "title": english_sentence,
                    "route": "/quiz/12",
                    "request_id": "req_priv_cli_1",
                    "app_build": "118",
                    "observed": f"TypeError: {english_sentence} student@example.com عبارت خصوصی دانش‌آموز",
                    "context": {
                        "error_name": "TypeError",
                        "error_message": english_sentence,
                        "extra_note": extra_note,
                        "stack": f"TypeError: {english_sentence}\n    at renderQuiz (quiz.tsx:42:9)",
                    },
                },
                format="json",
            )
            self.assertEqual(r_cli.status_code, 200)

        self.assertGreaterEqual(len(bale_messages), 2)
        srv_group = ErrorGroup.objects.get(source=ErrorGroup.Source.SERVER, code="unhandled_exception")
        cli_group = ErrorGroup.objects.get(source=ErrorGroup.Source.CLIENT, code="js_error")

        for g, req_id, expected_type, expected_loc, expected_file in (
            (srv_group, "req_priv_srv_1", "ValueError", "/api/v1/search/", "tests.py"),
            (cli_group, "req_priv_cli_1", "TypeError", "/quiz/<id>", "quiz.tsx:42:9"),
        ):
            ev = g.events.first()
            report = build_ai_report(g)
            blob = "\n".join([g.title, g.observed, ev.observed, str(ev.evidence), report, *bale_messages])
            self.assertNotIn("passive voice", blob)
            self.assertNotIn("extra_note", blob)
            self.assertNotIn("یادداشت آزمایشی", blob)
            self.assertNotIn("student@example.com", blob)
            self.assertNotIn("عبارت خصوصی دانش‌آموز", blob)
            self.assertIn(expected_type, report)
            self.assertIn(expected_loc, report)
            self.assertIn(expected_file, report)
            self.assertIn(req_id, report)
            self.assertTrue(ev.app_build)

    def test_sanitization_scrubs_pii_secrets_and_disallowed_context(self):
        self.client.force_authenticate(user=self.user)
        r = self.client.post(
            "/api/v1/diagnostics/events/",
            {
                "event_id": "evt_scrub_1",
                "kind": "client_error",
                "code": "js_error",
                "title": "خطا برای 09121112233 با Bearer supersecrettoken123",
                "route": "/section/42?token=abc123secret&sig=deadbeef",
                "observed": "ارسال به ?sig=verysecret99&exp=123 برای 09129998877 شکست خورد",
                "install_id": "inst_1",
                "context": {
                    "book_slug": "bio-1",
                    "error_message": "Bearer abcdef1234567890 failed for 09121112233",
                    "quote": "متن محرمانه یادداشت دانشجو",
                    "stem": "صورت سؤال پولی کتاب",
                    "phone": "09121112233",
                    "token": "secret-jwt",
                },
                "breadcrumbs": [{"at": "2026-11-24T10:00:00Z", "type": "api", "name": "GET /section/42", "detail": "09121112233"}],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        ev = ErrorEvent.objects.get(event_id="evt_scrub_1")
        self.assertTrue(ev.user_ref.startswith("u-"))
        self.assertNotIn("09121112233", ev.user_ref)
        ctx = ev.evidence.get("context", {})
        self.assertEqual(ctx.get("book_slug"), "bio-1")
        self.assertNotIn("quote", ctx)
        self.assertNotIn("stem", ctx)
        self.assertNotIn("phone", ctx)
        self.assertNotIn("token", ctx)

        report = build_ai_report(ev.group)
        for sensitive in ("09121112233", "09129998877", "supersecrettoken123", "abcdef1234567890", "verysecret99", "متن محرمانه", "صورت سؤال پولی"):
            self.assertNotIn(sensitive, report)

    def test_web_version_mismatch_clue_and_resolved_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "build-commit.txt").write_text("newsha999\n", encoding="utf-8")
            with override_settings(WEBAPP_DIR=Path(tmp)):
                r = self.client.post(
                    "/api/v1/diagnostics/events/",
                    {
                        "event_id": "evt_web_old_1",
                        "kind": "client_error",
                        "code": "react_render",
                        "title": "خطای رندر وب",
                        "route": "/book/calculus-1",
                        "install_id": "inst_web_1",
                    },
                    HTTP_X_APP_PLATFORM="web",
                    HTTP_X_APP_CHANNEL="official",
                    HTTP_X_APP_WEB_COMMIT="oldsha111",
                    format="json",
                )
        self.assertEqual(r.status_code, 200)
        ev = ErrorEvent.objects.get(event_id="evt_web_old_1")
        self.assertTrue(ev.version_mismatch)
        self.assertEqual(ev.server_version, "newsha999")
        self.assertEqual(ev.route, "/book/<slug>")
        report = build_ai_report(ev.group)
        self.assertIn("نسخهٔ وب‌اپ با نسخهٔ سرور متفاوت بوده است", report)

        group = ev.group
        group.status = ErrorGroup.Status.RESOLVED
        group.resolved_at = timezone.now()
        group.save()

        # New occurrence reopens a resolved group.
        self.client.post(
            "/api/v1/diagnostics/events/",
            {"event_id": "evt_web_old_2", "kind": "client_error", "code": "react_render", "title": "خطای رندر وب", "route": "/book/phys-1"},
            format="json",
        )
        group.refresh_from_db()
        self.assertEqual(group.status, ErrorGroup.Status.OPEN)
        self.assertIsNone(group.resolved_at)

    def test_rate_limiting_blocks_install_flood(self):
        with override_settings():
            from apps.diagnostics import views as diag_views

            orig = diag_views.EVENTS_PER_INSTALL_PER_HOUR
            diag_views.EVENTS_PER_INSTALL_PER_HOUR = 2
            try:
                for i in range(2):
                    r = self.client.post(
                        "/api/v1/diagnostics/events/",
                        {"event_id": f"evt_rl_{i}", "code": "js_error", "title": "err", "install_id": "inst_rl"},
                        format="json",
                    )
                    self.assertEqual(r.status_code, 200)
                r3 = self.client.post(
                    "/api/v1/diagnostics/events/",
                    {"event_id": "evt_rl_2", "code": "js_error", "title": "err", "install_id": "inst_rl"},
                    format="json",
                )
                self.assertEqual(r3.status_code, 429)
            finally:
                diag_views.EVENTS_PER_INSTALL_PER_HOUR = orig


class DiagnosticsMiddlewareTests(TestCase):
    def test_middleware_attaches_request_id_and_records_unhandled_exception(self):
        rf = RequestFactory()
        mw_ok = RequestDiagnosticsMiddleware(lambda req: HttpResponse("ok"))
        req_ok = rf.get("/api/v1/majors/")
        resp = mw_ok(req_ok)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["X-Request-Id"])

        def exploding_view(request):
            raise RuntimeError("boom for 09123334455")

        mw_err = RequestDiagnosticsMiddleware(exploding_view)
        req_err = rf.post("/api/v1/me/reviews/77/finish/", HTTP_X_REQUEST_ID="req_custom_1", HTTP_X_APP_OP_ID="op_99")
        req_err.user = User.objects.create_user(phone="09123334455", password="pass")
        # 404 / 403 exceptions must not be recorded as 500 server exceptions.
        from django.core.exceptions import PermissionDenied
        from django.http import Http404

        mw_err.process_exception(req_err, Http404("not found"))
        mw_err.process_exception(req_err, PermissionDenied("forbidden"))
        self.assertFalse(ErrorGroup.objects.filter(source=ErrorGroup.Source.SERVER).exists())

        mw_err.process_exception(req_err, RuntimeError("boom for 09123334455"))

        group = ErrorGroup.objects.get(source=ErrorGroup.Source.SERVER, code="unhandled_exception")
        self.assertEqual(group.severity, ErrorGroup.Severity.CRITICAL)
        self.assertEqual(group.route, "/api/v1/me/reviews/<id>/finish/")
        ev = group.events.first()
        self.assertEqual(ev.request_id, "req_custom_1")
        self.assertEqual(ev.op_id, "op_99")
        self.assertNotIn("09123334455", group.title)


class HealthCheckAcceptanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="09125556677", password="pass")
        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="فیزیک", slug="physics-1", is_published=True, price=100000)
        self.chapter = self.book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل ۱", slug="ch-1", position=1, is_published=True)
        self.section = self.chapter.add_child(kind=ContentNode.Kind.SECTION, title="بخش ۱", slug="sec-1", is_published=True)
        self.plan1 = Plan.objects.create(title="اشتراک ۱ ماهه", scope=Plan.Scope.ALL, months=1, price=100000, is_active=True)
        self.plan2 = Plan.objects.create(title="اشتراک ۲ ماهه", scope=Plan.Scope.ALL, months=2, price=180000, is_active=True)

    def test_payment_health_check_separates_valid_renewal_and_cancelled_from_broken_orders(self):
        now = timezone.now()
        # 1. Healthy initial subscription (1 month = 30d)
        o1 = Order.objects.create(
            user=self.user, plan=self.plan1, title=self.plan1.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.ALL, status=Order.Status.PAID, paid_at=now, track_id="t-ok-1",
        )
        e1 = Entitlement.objects.create(
            user=self.user, all_majors=True, starts_at=now, ends_at=now + timedelta(days=30), order=o1,
        )
        # 2. Healthy stacked renewal (starts at e1.ends_at, lasts 60 days)
        o2 = Order.objects.create(
            user=self.user, plan=self.plan2, title=self.plan2.title, amount=180000,
            plan_months=2, plan_scope=Plan.Scope.ALL, status=Order.Status.PAID, paid_at=now, track_id="t-ok-2",
        )
        Entitlement.objects.create(
            user=self.user, all_majors=True, starts_at=e1.ends_at, ends_at=e1.ends_at + timedelta(days=60), order=o2,
        )
        # 3. Healthy order whose entitlement was later cancelled (is_archived=True) & expired
        o3 = Order.objects.create(
            user=self.user, plan=self.plan1, title=self.plan1.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.ALL, status=Order.Status.PAID, paid_at=now - timedelta(days=40), track_id="t-ok-3",
        )
        Entitlement.objects.create(
            user=self.user, all_majors=True, starts_at=now - timedelta(days=40), ends_at=now - timedelta(days=10),
            order=o3, is_archived=True,
        )
        # 4. Refunded order (ignored) and pending order with track_id (counted as pending, NOT critical)
        Order.objects.create(
            user=self.user, book=self.book, title="خرید کتاب", amount=100000,
            status=Order.Status.REFUNDED, track_id="t-ref",
        )
        pending_old = Order.objects.create(
            user=self.user, book=self.book, title="خرید در انتظار", amount=100000,
            status=Order.Status.PENDING, track_id="t-pending",
        )
        Order.objects.filter(pk=pending_old.pk).update(created_at=now - timedelta(minutes=30))

        # 5. Two genuinely broken PAID orders: one missing entitlement, one wrong duration (15d instead of 30d)
        broken_missing = Order.objects.create(
            user=self.user, book=self.book, title="خرید کتاب خراب", amount=100000,
            status=Order.Status.PAID, paid_at=now, track_id="t-bad-missing",
        )
        broken_wrong = Order.objects.create(
            user=self.user, plan=self.plan1, title=self.plan1.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.ALL, status=Order.Status.PAID, paid_at=now, track_id="t-bad-wrong",
        )
        Entitlement.objects.create(
            user=self.user, all_majors=True, starts_at=now, ends_at=now + timedelta(days=15), order=broken_wrong,
        )

        run = check_payments_and_entitlements(now=now)
        self.assertTrue(run.completed)
        self.assertEqual(run.checked_count, 5)
        self.assertEqual(run.issues_found, 2)
        self.assertEqual(run.pending_count, 1)
        self.assertEqual(set(run.details["missing_order_ids"]), {broken_missing.id})
        self.assertEqual(set(run.details["wrong_order_ids"]), {broken_wrong.id})
        self.assertTrue(ErrorGroup.objects.filter(code="paid_order_missing_entitlement").exists())
        self.assertTrue(ErrorGroup.objects.filter(code="paid_order_wrong_entitlement").exists())
        # Running again the same day is idempotent on event_count.
        check_payments_and_entitlements(now=now)
        self.assertEqual(ErrorGroup.objects.get(code="paid_order_missing_entitlement").event_count, 1)

        # verify_settled_order also works cleanly on a valid order.
        self.assertTrue(verify_settled_order(o2.id))

    def test_payment_health_check_catches_wrong_owner_and_wrong_major_scope(self):
        now = timezone.now()
        other_user = User.objects.create_user(phone="09128889900", password="pass")
        m_math = Major.objects.create(name="ریاضی", slug="math")
        m_bio = Major.objects.create(name="تجربی", slug="bio")
        major_plan = Plan.objects.create(title="اشتراک ۱ ماهه رشته‌ای", scope=Plan.Scope.MAJOR, months=1, price=100000, is_active=False)

        # Two orders with same price & duration:
        # 1. Book order whose entitlement points to the right book & forever, but belongs to another user!
        o_wrong_owner = Order.objects.create(
            user=self.user, book=self.book, title="خرید کتاب", amount=100000,
            status=Order.Status.PAID, paid_at=now, track_id="t-owner-bad",
        )
        Entitlement.objects.create(user=other_user, book=self.book, order=o_wrong_owner)

        # 2. Major-scoped subscription order whose entitlement points to the wrong major!
        o_wrong_major = Order.objects.create(
            user=self.user, plan=major_plan, major=m_math, title=major_plan.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.MAJOR, status=Order.Status.PAID, paid_at=now, track_id="t-major-bad",
        )
        Entitlement.objects.create(
            user=self.user, major=m_bio, all_majors=False, starts_at=now, ends_at=now + timedelta(days=30), order=o_wrong_major,
        )

        # 3. Healthy major-scoped renewal + later cancelled order with identical price & duration
        o_ok_1 = Order.objects.create(
            user=self.user, plan=major_plan, major=m_math, title=major_plan.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.MAJOR, status=Order.Status.PAID, paid_at=now, track_id="t-major-ok-1",
        )
        e_ok_1 = Entitlement.objects.create(
            user=self.user, major=m_math, all_majors=False, starts_at=now, ends_at=now + timedelta(days=30), order=o_ok_1,
        )
        o_ok_2 = Order.objects.create(
            user=self.user, plan=major_plan, major=m_math, title=major_plan.title, amount=100000,
            plan_months=1, plan_scope=Plan.Scope.MAJOR, status=Order.Status.PAID, paid_at=now, track_id="t-major-ok-2",
        )
        Entitlement.objects.create(
            user=self.user, major=m_math, all_majors=False, starts_at=e_ok_1.ends_at, ends_at=e_ok_1.ends_at + timedelta(days=30),
            order=o_ok_2, is_archived=True,
        )

        run = check_payments_and_entitlements(now=now)
        self.assertEqual(run.checked_count, 4)
        self.assertEqual(run.issues_found, 2)
        self.assertEqual(set(run.details["wrong_order_ids"]), {o_wrong_owner.id, o_wrong_major.id})

    def test_review_health_check_catches_silent_score_mismatch_without_false_positives(self):
        q1 = Question.objects.create(node=self.section, slug="q1", stem="s1", explanation="e1", difficulty=Question.Difficulty.EASY)
        c1_right = Choice.objects.create(question=q1, text="A", is_correct=True, order=0)
        c1_wrong = Choice.objects.create(question=q1, text="B", is_correct=False, order=1)
        q2 = Question.objects.create(node=self.section, slug="q2", stem="s2", explanation="e2", difficulty=Question.Difficulty.EASY)
        Choice.objects.create(question=q2, text="C", is_correct=True, order=0)
        q3 = Question.objects.create(node=self.section, slug="q3", stem="s3", explanation="e3", difficulty=Question.Difficulty.EASY)

        cr = ChapterReview.objects.create(
            user=self.user, chapter=self.chapter, book=self.book, finished_at=timezone.now(), due_on=timezone.localdate()
        )
        now = timezone.now()

        # Legacy migration-0016 closed session without score -> ignored cleanly
        ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[q1.id], finished_at=now, score=None)

        # Healthy session, even after a later answer-key edit on q1!
        s_ok = ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[q1.id, q2.id], finished_at=now, score=0.5)
        QuizAnswer.objects.create(user=self.user, question=q1, choice_order=0, was_correct=True, review_session=s_ok)
        QuizAnswer.objects.create(user=self.user, question=q2, choice_order=1, was_correct=False, review_session=s_ok)
        c1_right.is_correct = False
        c1_right.save()
        c1_wrong.is_correct = True
        c1_wrong.save()

        # Silent mismatch: answers are 1/2 (0.5) while ReviewSession.score says 1.0
        s_bad_score = ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[q1.id, q2.id], finished_at=now, score=1.0)
        QuizAnswer.objects.create(user=self.user, question=q1, choice_order=0, was_correct=True, review_session=s_bad_score)
        QuizAnswer.objects.create(user=self.user, question=q2, choice_order=1, was_correct=False, review_session=s_bad_score)

        # Silent orphan answer: QuizAnswer attached to session for question q3 NOT in served
        s_orphan = ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[q1.id], finished_at=now, score=1.0)
        QuizAnswer.objects.create(user=self.user, question=q3, choice_order=0, was_correct=True, review_session=s_orphan)

        run = check_review_sessions(now=now)
        self.assertTrue(run.completed)
        self.assertEqual(run.checked_count, 3)
        self.assertEqual(run.issues_found, 2)
        self.assertEqual(set(run.details["mismatched_session_ids"]), {s_bad_score.id, s_orphan.id})

        score_group = ErrorGroup.objects.get(code="review_score_mismatch")
        ev = score_group.events.first()
        self.assertEqual(ev.evidence["context"]["expected_score"], 0.5)
        self.assertEqual(ev.evidence["context"]["recorded_score"], 1.0)
        self.assertIn("0.5", score_group.observed)
        self.assertIn("1.0", score_group.observed)

    def test_review_health_check_ignores_legacy_pre_0016_scored_sessions_and_catches_new_missing_answers(self):
        cr = ChapterReview.objects.create(
            user=self.user, chapter=self.chapter, book=self.book, finished_at=timezone.now(), due_on=timezone.localdate()
        )
        now = timezone.now()

        # Legacy completed scored session from before migration 0016 (`QuizAnswer.review_session`) -> skipped cleanly
        s_legacy = ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[1, 2], finished_at=now - timedelta(days=5), score=0.5)
        ReviewSession.objects.filter(pk=s_legacy.pk).update(started_at=now - timedelta(days=5), finished_at=now - timedelta(days=5))

        # New completed scored session with genuinely missing answers -> definitive alert
        s_new_missing = ReviewSession.objects.create(user=self.user, chapter_review=cr, served=[1, 2], finished_at=now, score=1.0)

        run = check_review_sessions(now=now)

        self.assertEqual(run.checked_count, 1)
        self.assertEqual(run.issues_found, 1)
        self.assertEqual(run.details["mismatched_session_ids"], [s_new_missing.id])
        self.assertEqual(run.details["legacy_skipped"], 1)

    def test_offline_summary_retention_and_management_command(self):
        now = timezone.now()
        ev_old, _ = record_event(
            source=ErrorGroup.Source.CLIENT,
            kind=ErrorGroup.Kind.OFFLINE,
            code="offline_missing",
            title="فایل بسته پیدا نشد",
            event_id="evt_off_old",
            created_at=now - timedelta(days=90),
        )
        record_event(
            source=ErrorGroup.Source.CLIENT,
            kind=ErrorGroup.Kind.OFFLINE,
            code="offline_missing",
            title="فایل بسته پیدا نشد",
            event_id="evt_off_new",
            created_at=now,
        )
        deleted = prune_old_events(now=now)
        self.assertEqual(deleted, 1)
        self.assertFalse(ErrorEvent.objects.filter(pk=ev_old.pk).exists())
        self.assertTrue(ErrorEvent.objects.filter(event_id="evt_off_new").exists())

        off_run = check_offline_health(now=now)
        self.assertEqual(off_run.details["offline_missing"], 1)

        call_command("check_health")
        self.assertGreaterEqual(HealthCheckRun.objects.count(), 4)
        runs = run_all_health_checks(now=now)
        self.assertEqual(len(runs), 3)

        from apps.catalog.backups import run_due

        HealthCheckRun.objects.all().delete()
        with (
            mock.patch("apps.catalog.backups.backup_database"),
            mock.patch("apps.catalog.backups.backup_media"),
        ):
            run_due(now=now)
        self.assertEqual(HealthCheckRun.objects.count(), 3)


class DiagnosticsAdminTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(phone="09120001111", password="pass", is_staff=True, is_superuser=False)
        self.super = User.objects.create_superuser(phone="09120002222", password="pass")
        self.ev, _ = record_event(
            source=ErrorGroup.Source.CLIENT,
            kind=ErrorGroup.Kind.OFFLINE,
            code="offline_corrupt",
            title="بسته باز نشد",
            event_id="evt_adm_1",
            install_id="inst_adm_1",
            expected="بسته سالم باز شود",
            observed="رمزگشایی شکست خورد",
            context={"book_slug": "math-1"},
        )

    def test_admin_views_are_superuser_only_and_render_ai_report(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get("/admin/diagnostics/errorgroup/").status_code, 403)
        self.assertEqual(self.client.post("/admin/diagnostics/errorgroup/run-checks/").status_code, 403)

        self.client.force_login(self.super)
        changelist = self.client.get("/admin/diagnostics/errorgroup/")
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, "اجرای بررسی سلامت همین حالا")
        self.assertContains(changelist, "بسته باز نشد")

        detail = self.client.get(f"/admin/diagnostics/errorgroup/{self.ev.group_id}/change/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "کپی گزارش برای هوش مصنوعی")
        self.assertContains(detail, "انتظار محصول")
        self.assertContains(detail, "evt_adm_1")

        res_run = self.client.post("/admin/diagnostics/errorgroup/run-checks/")
        self.assertEqual(res_run.status_code, 302)
        self.assertEqual(HealthCheckRun.objects.count(), 3)

        res_status = self.client.post(
            f"/admin/diagnostics/errorgroup/{self.ev.group_id}/set-status/",
            {"status": ErrorGroup.Status.RESOLVED},
        )
        self.assertEqual(res_status.status_code, 302)
        self.ev.group.refresh_from_db()
        self.assertEqual(self.ev.group.status, ErrorGroup.Status.RESOLVED)
        self.assertIsNotNone(self.ev.group.resolved_at)
