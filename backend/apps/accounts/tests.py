from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import DeviceSession, OTPCode, User
from .phone import InvalidPhone, normalize_phone


class PhoneTests(TestCase):
    def test_accepts_common_forms(self):
        for raw in ["09121234567", "+989121234567", "00989121234567", "9121234567", "۰۹۱۲ ۱۲۳ ۴۵۶۷", "0912-123-4567"]:
            self.assertEqual(normalize_phone(raw), "09121234567", raw)

    def test_rejects_invalid(self):
        for raw in ["", "0212345678", "0912123456", "abc", "091212345678"]:
            with self.assertRaises(InvalidPhone, msg=raw):
                normalize_phone(raw)


@override_settings(SMS_BACKEND="console")
class OTPFlowTests(TestCase):
    phone = "09121234567"

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _request_code(self, phone=None):
        with mock.patch("apps.accounts.sms.send_sms") as send:
            response = self.client.post("/api/v1/auth/request-otp/", {"phone": phone or self.phone}, format="json")
        code = None
        if send.called:
            code = send.call_args[0][1].split(": ")[1].split("\n")[0]
        return response, code

    def _verify(self, code, **extra):
        return self.client.post("/api/v1/auth/verify-otp/", {"phone": self.phone, "code": code, **extra}, format="json")

    def test_full_login_creates_user_and_session(self):
        response, code = self._request_code()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(code), 6)
        response = self._verify(code, device_name="Pixel 8", platform="android")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(phone=self.phone).exists())
        token = response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me = self.client.get("/api/v1/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["phone"], self.phone)

    def test_code_and_token_are_not_stored_in_plain_text(self):
        _, code = self._request_code()
        otp = OTPCode.objects.get()
        self.assertNotIn(code, otp.code_hash)
        token = self._verify(code).data["token"]
        self.assertFalse(DeviceSession.objects.filter(token_hash=token).exists())

    def test_cooldown_blocks_immediate_resend(self):
        self._request_code()
        response, code = self._request_code()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "cooldown")
        self.assertIsNone(code)

    def test_sms_carries_app_hash_and_fits_one_sms(self):
        with mock.patch("apps.accounts.sms.send_sms") as send:
            self.client.post("/api/v1/auth/request-otp/", {"phone": self.phone, "app_hash": "FA+9qCX9VSu"}, format="json")
        text = send.call_args[0][1]
        self.assertTrue(text.startswith("لیموخوان"))
        self.assertTrue(text.endswith("\nFA+9qCX9VSu"))
        self.assertLessEqual(len(text), 70)

    def test_bad_app_hash_is_ignored(self):
        with mock.patch("apps.accounts.sms.send_sms") as send:
            self.client.post("/api/v1/auth/request-otp/", {"phone": self.phone, "app_hash": "<script>"}, format="json")
        self.assertNotIn("script", send.call_args[0][1])

    def test_hourly_limit_says_when_to_try_again(self):
        from datetime import timedelta

        from django.utils import timezone

        for minutes_ago in (50, 40, 30, 20, 10):
            otp, _ = OTPCode.issue(self.phone)
            OTPCode.objects.filter(pk=otp.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
        response, code = self._request_code()
        self.assertEqual(response.status_code, 429)
        self.assertIsNone(code)
        self.assertIn("۱۰ دقیقه", response.data["message"])
        self.assertTrue(540 <= response.data["retry_after"] <= 601)

    def test_wrong_code_counts_attempts_and_locks(self):
        _, code = self._request_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self._verify(wrong).data["code"], "otp_wrong")
        # Even the right code fails once attempts are used up.
        self.assertEqual(self._verify(code).data["code"], "otp_expired")

    def test_expired_code_rejected(self):
        _, code = self._request_code()
        OTPCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._verify(code).data["code"], "otp_expired")

    def test_code_cannot_be_reused(self):
        _, code = self._request_code()
        self.assertEqual(self._verify(code).status_code, 200)
        self.assertEqual(self._verify(code).data["code"], "otp_expired")

    def test_sms_failure_does_not_leave_a_code(self):
        from .sms import SMSError

        with mock.patch("apps.accounts.sms.send_sms", side_effect=SMSError("down")):
            response = self.client.post("/api/v1/auth/request-otp/", {"phone": self.phone}, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(OTPCode.objects.exists())

    def _login(self, device):
        OTPCode.objects.all().delete()
        _, code = self._request_code()
        return self._verify(code, device_name=device)

    def test_third_device_must_replace_one(self):
        first = self._login("phone")
        self._login("laptop")
        third = self._login("tablet")
        self.assertEqual(third.status_code, 409)
        self.assertEqual(third.data["code"], "session_limit")
        self.assertEqual(len(third.data["sessions"]), 2)

        # Choosing a session to sign out lets the third device in, with the same code.
        code_response = self._verify
        OTPCode.objects.all().delete()
        _, code = self._request_code()
        replaced = code_response(code, device_name="tablet", replace_session_id=first.data["session_id"])
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(DeviceSession.active_for(User.objects.get()).count(), 2)

        # The replaced device is signed out.
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {first.data['token']}")
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)

    def test_logout_revokes_token(self):
        token = self._login("phone").data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.post("/api/v1/auth/logout/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)

    def test_user_can_list_and_revoke_own_sessions_only(self):
        phone_login = self._login("phone")
        laptop_login = self._login("laptop")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {laptop_login.data['token']}")
        sessions = self.client.get("/api/v1/me/sessions/").data
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(s["is_current"] for s in sessions), 1)

        other = User.objects.create_user("09350000000")
        foreign, _ = DeviceSession.start(other, "x")
        self.assertEqual(self.client.post(f"/api/v1/me/sessions/{foreign.id}/revoke/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/me/sessions/{phone_login.data['session_id']}/revoke/").status_code, 200)
        self.assertEqual(len(self.client.get("/api/v1/me/sessions/").data), 1)

    def test_expired_session_token_rejected(self):
        token = self._login("phone").data["token"]
        DeviceSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)

    def test_spoofed_forwarded_for_does_not_bypass_ip_limit(self):
        with override_settings(OTP_REQUESTS_PER_IP_PER_HOUR=3):
            statuses = []
            for i in range(5):
                with mock.patch("apps.accounts.sms.send_sms"):
                    r = self.client.post(
                        "/api/v1/auth/request-otp/",
                        {"phone": f"0912000000{i}"},
                        format="json",
                        HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
                    )
                statuses.append(r.status_code)
        self.assertEqual(statuses, [200, 200, 200, 429, 429])

    def test_daily_wrong_guess_cap_per_phone(self):
        with override_settings(OTP_MAX_WRONG_PER_DAY=6):
            _, code = self._request_code()
            for _ in range(5):
                self._verify("000000" if code != "000000" else "111111")
            OTPCode.objects.update(created_at=timezone.now() - timedelta(minutes=5))
            _, code = self._request_code()
            self._verify("000000" if code != "000000" else "111111")
            # Cap reached: even the correct code is refused for 24 hours.
            self.assertEqual(self._verify(code).status_code, 429)

    def test_wrong_guesses_limited_per_ip_across_phones(self):
        with override_settings(OTP_WRONG_PER_IP_PER_HOUR=2):
            for phone in ["09120000001", "09120000002", "09120000003"]:
                with mock.patch("apps.accounts.sms.send_sms"):
                    self.client.post("/api/v1/auth/request-otp/", {"phone": phone}, format="json")
            r1 = self.client.post("/api/v1/auth/verify-otp/", {"phone": "09120000001", "code": "999999"}, format="json")
            r2 = self.client.post("/api/v1/auth/verify-otp/", {"phone": "09120000002", "code": "999999"}, format="json")
            r3 = self.client.post("/api/v1/auth/verify-otp/", {"phone": "09120000003", "code": "999999"}, format="json")
        self.assertEqual([r1.status_code, r2.status_code, r3.status_code], [400, 400, 429])

    def test_invalid_profile_update_returns_400(self):
        token = self._login("phone").data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.patch("/api/v1/me/", {"first_name": "x" * 80}, format="json").status_code, 400)
        self.assertEqual(self.client.patch("/api/v1/me/", {"email": "bad"}, format="json").status_code, 400)
        ok = self.client.patch("/api/v1/me/", {"first_name": "حامد"}, format="json")
        self.assertEqual(ok.data["first_name"], "حامد")

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/api/v1/health/").status_code, 200)


class AdminLoginThrottleTests(TestCase):
    def test_password_guessing_is_blocked(self):
        User.objects.create_superuser("09120000009", password="Right-Pass-123")
        c = Client()
        for _ in range(5):
            r = c.post("/admin/login/", {"username": "09120000009", "password": "wrong"})
            self.assertEqual(r.status_code, 200)
        r = c.post("/admin/login/", {"username": "09120000009", "password": "Right-Pass-123"})
        self.assertEqual(r.status_code, 429)


class AdminOTPLoginTests(TestCase):
    """Django admin uses SMS OTP for active staff; only a superuser may use the password break-glass path."""

    def setUp(self):
        self.staff = User.objects.create_user("09120000601", is_staff=True)
        self.client = Client()

    def request_code(self, phone=None, next_url=""):
        with mock.patch("apps.accounts.admin_login.send_login_code") as send:
            response = self.client.post(
                "/admin/login/",
                {"action": "send_otp", "phone": phone or self.staff.phone, "next": next_url},
            )
        code = send.call_args.args[1] if send.called else None
        return response, code, send

    def test_login_page_has_sms_and_superuser_only_break_glass_forms(self):
        page = self.client.get("/admin/login/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ورود با پیامک")
        self.assertContains(page, "ورود اضطراری با گذرواژه (فقط مدیر کل)")
        self.assertContains(page, 'name="action" value="send_otp"')

    def test_active_staff_can_sign_in_with_a_single_use_otp(self):
        response, code, send = self.request_code(next_url="https://evil.example/steal")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(send.called)
        self.assertEqual(OTPCode.objects.filter(phone=self.staff.phone).count(), 1)

        response = self.client.post("/admin/login/", {
            "action": "verify_otp", "phone": self.staff.phone, "code": code,
            "next": "https://evil.example/steal",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.staff.pk)
        self.assertIsNotNone(OTPCode.objects.get(phone=self.staff.phone).consumed_at)
        self.assertFalse(DeviceSession.objects.filter(user=self.staff).exists())

        replay = Client()
        session = replay.session
        session["admin_login_phone"] = self.staff.phone
        session.save()
        response = replay.post("/admin/login/", {
            "action": "verify_otp", "phone": self.staff.phone, "code": code,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", replay.session)

    def test_non_staff_and_unknown_numbers_get_no_sms_and_create_no_account(self):
        learner = User.objects.create_user("09120000602")
        response, code, send = self.request_code(learner.phone)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(code)
        send.assert_not_called()
        self.assertFalse(OTPCode.objects.filter(phone=learner.phone).exists())

        unknown = "09120000603"
        response, code, send = self.request_code(unknown)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(code)
        send.assert_not_called()
        self.assertFalse(User.objects.filter(phone=unknown).exists())

    def test_valid_sms_code_cannot_sign_in_a_learner(self):
        learner = User.objects.create_user("09120000604")
        self.request_code(learner.phone)
        _otp, code = OTPCode.issue(learner.phone)  # even a code from the public learner flow grants no admin access
        response = self.client.post("/admin/login/", {
            "action": "verify_otp", "phone": learner.phone, "code": code,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_staff_cannot_request_or_use_an_otp(self):
        inactive = User.objects.create_user("09120000606", is_staff=True, is_active=False)
        response, code, send = self.request_code(inactive.phone)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(code)
        send.assert_not_called()
        _otp, code = OTPCode.issue(inactive.phone)
        response = self.client.post("/admin/login/", {
            "action": "verify_otp", "phone": inactive.phone, "code": code,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_post_is_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/admin/login/", {
            "action": "send_otp", "phone": self.staff.phone,
        })
        self.assertEqual(response.status_code, 403)

    def test_wrong_otp_attempts_use_the_shared_ip_and_code_limits(self):
        with override_settings(OTP_WRONG_PER_IP_PER_HOUR=2):
            _response, code, _send = self.request_code()
            wrong = "000000" if code != "000000" else "111111"
            for _ in range(2):
                response = self.client.post("/admin/login/", {
                    "action": "verify_otp", "phone": self.staff.phone, "code": wrong,
                })
                self.assertEqual(response.status_code, 200)
            response = self.client.post("/admin/login/", {
                "action": "verify_otp", "phone": self.staff.phone, "code": code,
            })
            self.assertContains(response, "تلاش‌های ناموفق زیاد است")
            self.assertNotIn("_auth_user_id", self.client.session)
            self.assertEqual(OTPCode.objects.get(phone=self.staff.phone).attempts, 2)

    def test_staff_password_is_rejected_but_superuser_break_glass_works(self):
        self.staff.set_password("Staff-Password-123")
        self.staff.save(update_fields=["password"])
        response = self.client.post("/admin/login/", {
            "action": "password", "username": self.staff.phone, "password": "Staff-Password-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        boss = User.objects.create_superuser("09120000605", password="Boss-Password-123")
        response = self.client.post("/admin/login/", {
            "action": "password", "username": boss.phone, "password": "Boss-Password-123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), boss.pk)


class OtpHashSettingTests(TestCase):
    def test_hash_line_can_be_turned_off(self):
        from django.test import override_settings

        from .views import _otp_message

        self.assertTrue(_otp_message("123456", "AbCdEfGhIjK").endswith("\nAbCdEfGhIjK"))
        with override_settings(OTP_SMS_APP_HASH=False):
            self.assertNotIn("AbCdEfGhIjK", _otp_message("123456", "AbCdEfGhIjK"))


class PanelLoginTests(TestCase):
    """«باز کردن وب اپ با حساب من»: panel → one-time code in the fragment → session, staff only, once, for a minute."""

    def setUp(self):
        self.staff = User.objects.create_superuser("09120000501", password="x-Strong-pass-1")
        self.web = Client()
        self.web.force_login(self.staff)
        self.api = APIClient()

    def _code(self):
        with override_settings(APP_URL="https://app.example.ir"):
            r = self.web.post("/admin/open-app/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("https://app.example.ir/panel-login#"))
        self.assertEqual(r["Cache-Control"], "no-store")
        return r["Location"].split("#", 1)[1]

    def _login(self, code, **extra):
        return self.api.post("/api/v1/auth/panel-login/", {"code": code, "device_name": "مرورگر وب", "platform": "web", **extra}, format="json")

    def test_code_signs_in_once(self):
        from .models import PanelLoginCode

        code = self._code()
        self.assertFalse(PanelLoginCode.objects.filter(code_hash=code).exists())  # only the hash is stored
        r = self._login(code)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["user"]["is_staff"])
        me = APIClient(HTTP_AUTHORIZATION=f"Bearer {r.data['token']}").get("/api/v1/me/")
        self.assertEqual(me.data["phone"], "09120000501")
        self.assertEqual(self._login(code).data["code"], "panel_code_invalid")  # used

    def test_a_relative_app_url_goes_to_the_host_that_serves_the_web_app(self):
        """The panel is often opened on the website's own host, where no web app is served: the code must
        still reach the web app (the main host), not a 404 there."""
        with override_settings(APP_URL="/", SITE_URL="https://api.example.ir"):
            r = self.web.post("/admin/open-app/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("https://api.example.ir/panel-login#"), r["Location"])

    def test_only_post_and_only_staff(self):
        self.assertEqual(self.web.get("/admin/open-app/").status_code, 405)
        anon = Client().post("/admin/open-app/")
        self.assertEqual(anon.status_code, 302)
        self.assertIn("/admin/login/", anon["Location"])
        learner = User.objects.create_user("09120000502")
        c = Client()
        c.force_login(learner)
        r = c.post("/admin/open-app/")
        self.assertIn("/admin/login/", r["Location"])

    def test_code_expires_and_dies_with_staff_rights(self):
        from .models import PanelLoginCode

        code = self._code()
        PanelLoginCode.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self._login(code).data["code"], "panel_code_invalid")
        code = self._code()
        User.objects.filter(pk=self.staff.pk).update(is_staff=False)
        self.assertEqual(self._login(code).data["code"], "panel_code_invalid")

    def test_wrong_codes_count_toward_the_ip_limit(self):
        with override_settings(OTP_WRONG_PER_IP_PER_HOUR=3):
            for _ in range(3):
                self.assertEqual(self._login("nope").data["code"], "panel_code_invalid")
            self.assertEqual(self._login(self._code()).status_code, 429)

    def test_device_limit_keeps_the_code_for_a_choice(self):
        DeviceSession.start(self.staff, "گوشی", "android")
        old, _ = DeviceSession.start(self.staff, "لپ‌تاپ", "web")
        code = self._code()
        r = self._login(code)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(r.data["sessions"]), 2)
        r = self._login(code, replace_session_id=old.id)
        self.assertEqual(r.status_code, 200)
        old.refresh_from_db()
        self.assertIsNotNone(old.revoked_at)

    def test_panel_shows_the_button(self):
        page = self.web.get("/admin/")
        self.assertContains(page, "وب‌اپ")
        self.assertContains(page, "lp.nav.scroll")


@override_settings(SMS_BACKEND="raygan", RAYGAN_ACCESS_HASH="hash-1", RAYGAN_OTP_PATTERN_ID="pattern-1")
class PatternSMSTests(TestCase):
    """Login codes through RayganSMS's approved pattern (service line, no promotional permit needed)."""

    def setUp(self):
        cache.clear()

    def answer(self, text, status_code=200):
        return mock.Mock(status_code=status_code, text=text)

    def test_login_code_goes_through_the_pattern(self):
        with mock.patch("apps.accounts.sms.requests.post", return_value=self.answer("604871999")) as post, \
                mock.patch("apps.accounts.sms._send_raygan") as line:
            response = self.client.post("/api/v1/auth/request-otp/", {"phone": "09121234567"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        line.assert_not_called()
        url, data = post.call_args.args[0], post.call_args.kwargs["data"]
        self.assertIn("SendPatternCodeWithUrl", url)
        self.assertEqual((data["AccessHash"], data["PatternId"], data["Mobile"]), ("hash-1", "pattern-1", "09121234567"))
        self.assertTrue(data["token1"].isdigit() and len(data["token1"]) == 6)

    def test_answers(self):
        from .sms import SMSError, SMSNotSent, _send_raygan_pattern

        for body, expected in (("3003", SMSNotSent), ("2003", SMSNotSent), ("5002", SMSError), ("0", SMSError), ("ok", SMSError)):
            with mock.patch("apps.accounts.sms.requests.post", return_value=self.answer(body)):
                with self.assertRaises(expected) as caught:
                    _send_raygan_pattern("09121234567", "123456")
                if expected is SMSError:
                    self.assertNotIsInstance(caught.exception, SMSNotSent)
        with mock.patch("apps.accounts.sms.requests.post", return_value=self.answer("2726")):
            _send_raygan_pattern("09121234567", "123456")

    def test_a_refused_code_is_not_kept(self):
        with mock.patch("apps.accounts.sms.requests.post", return_value=self.answer("3003")):
            response = self.client.post("/api/v1/auth/request-otp/", {"phone": "09121234567"}, content_type="application/json")
        self.assertEqual(response.status_code, 502)
        from .models import OTPCode

        self.assertFalse(OTPCode.objects.exists())

    @override_settings(RAYGAN_OTP_PATTERN_ID="")
    def test_without_a_pattern_the_line_is_used(self):
        with mock.patch("apps.accounts.sms.send_sms") as line:
            self.client.post("/api/v1/auth/request-otp/", {"phone": "09121234567"}, content_type="application/json")
        self.assertIn("کد ورود", line.call_args.args[1])


class SessionIdleAndSwitchTests(TestCase):
    def test_a_month_unused_session_no_longer_counts_or_works(self):
        user = User.objects.create_user("09120000501")
        old, token = DeviceSession.start(user, "old phone")
        DeviceSession.objects.filter(pk=old.pk).update(last_seen_at=timezone.now() - timedelta(days=31))
        DeviceSession.start(user, "new phone")
        self.assertEqual(DeviceSession.active_for(user).count(), 1)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get("/api/v1/me/").status_code, 401)

    def test_many_new_devices_are_marked_in_the_panel(self):
        boss = User.objects.create_superuser("09120000502", password="x-Strong-pass-1")
        user = User.objects.create_user("09120000503")
        for i in range(5):
            DeviceSession.start(user, f"phone {i}")
        self.client.force_login(boss)
        page = self.client.get("/admin/accounts/user/?devices=many").content.decode()
        self.assertIn("09120000503", page)
        self.assertIn("تعویض زیاد دستگاه", page)
