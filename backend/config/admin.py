"""Project admin site: keep teacher/editor workflows separate from public-site content."""

from django.contrib.admin.apps import AdminConfig
from django.contrib.admin.sites import AdminSite
from django.urls import reverse


_TEACHER_WORKFLOW_MODELS = frozenset({
    ("catalog", "BookEditor"),
    ("catalog", "TeacherProfile"),
    ("website", "Classroom"),
    ("website", "ClassroomMember"),
    ("website", "TeacherApplication"),
    ("website", "TeacherInvitation"),
    ("website", "BookAccessRequest"),
    ("website", "BookAccessRequestEvent"),
    ("website", "BookAccessMember"),
    ("website", "BookAccessEvent"),
    ("website", "PublicationRequest"),
    ("website", "PublicationRequestEvent"),
})

# Models visible to a teacher in their standard workspace
_TEACHER_VISIBLE_MODELS = frozenset({
    # catalog
    ("catalog", "Book"),
    ("catalog", "Section"),
    ("catalog", "ChapterRevision"),
    ("catalog", "Label"),
    ("catalog", "ShareSettings"),
    ("catalog", "AIProvider"),
    ("catalog", "BookAssistantAuditLog"),
    ("catalog", "BookOpinion"),
    # commerce (royalty, wallet & payout)
    ("commerce", "TeacherWallet"),
    ("commerce", "PayoutRequest"),
    ("commerce", "TeacherBankAccount"),
    ("commerce", "OrderAuthorRevenue"),
    ("commerce", "WalletTransaction"),
    ("commerce", "PoolBookShare"),
    # learning
    ("learning", "Question"),
    ("learning", "Flashcard"),
    ("learning", "ExamSource"),
    ("learning", "Report"),
    # guard
    ("guard", "Tracker"),
    ("guard", "TraceHit"),
    # workflows
    ("teacher_workflows", "Classroom"),
    ("teacher_workflows", "ClassroomMember"),
    ("teacher_workflows", "PublicationRequest"),
    ("teacher_workflows", "TeacherProfile"),
})


class LimoAdminSite(AdminSite):
    """Group author, invitation, publication-review, and group-access workflows separately."""

    def _transform_teacher_app_list(self, raw_apps):
        """Re-organize app groups, rename categories, and order models specifically for teacher ergonomics."""
        # Buckets for teacher models
        authoring_models = []
        teaching_models = []
        assessment_models = []
        ai_models = []

        catalog_app = next((a for a in raw_apps if a["app_label"] == "catalog"), None)
        workflows_app = next((a for a in raw_apps if a["app_label"] == "teacher_workflows"), None)
        learning_app = next((a for a in raw_apps if a["app_label"] == "learning"), None)

        authoring_url = catalog_app["app_url"] if catalog_app else reverse("admin:index")
        teaching_url = workflows_app["app_url"] if workflows_app else reverse("admin:index")
        assessment_url = learning_app["app_url"] if learning_app else reverse("admin:index")

        # Collect models from all apps
        all_models = {}
        for app in raw_apps:
            for m in app["models"]:
                all_models[(app["app_label"], m["object_name"])] = m

        # 1. میز تألیف و کتاب‌ها (Authoring Desk)
        _AUTHORING_KEYS = [
            ("catalog", "Book"),
            ("catalog", "Section"),
            ("catalog", "Label"),
            ("catalog", "ChapterRevision"),
            ("teacher_workflows", "PublicationRequest"),
            ("teacher_workflows", "TeacherProfile"),
            ("guard", "Tracker"),
            ("guard", "TraceHit"),
        ]
        for key in _AUTHORING_KEYS:
            if key in all_models:
                m_item = dict(all_models[key])
                if key == ("guard", "Tracker"):
                    m_item["name"] = "ردیاب محتوای من (حفاظت اثر)"
                elif key == ("guard", "TraceHit"):
                    m_item["name"] = "تاریخچه ردیابی‌های من"
                authoring_models.append(m_item)

        # 2. مدیریت کلاس‌ها و دوره‌ها (Classrooms & Students)
        _TEACHING_KEYS = [
            ("teacher_workflows", "Classroom"),
            ("teacher_workflows", "ClassroomMember"),
        ]
        for key in _TEACHING_KEYS:
            if key in all_models:
                teaching_models.append(all_models[key])

        # 3. ارزیابی، تمرین و بازخورد (Assessment & Feedback)
        _ASSESSMENT_KEYS = [
            ("catalog", "BookOpinion"),
            ("learning", "Question"),
            ("learning", "Flashcard"),
            ("learning", "ExamSource"),
            ("learning", "Report"),
        ]
        for key in _ASSESSMENT_KEYS:
            if key in all_models:
                assessment_models.append(all_models[key])

        # 4. دستیار و هوش مصنوعی (AI & Assistant)
        _AI_KEYS = [
            ("catalog", "AIProvider"),
            ("catalog", "BookAssistantAuditLog"),
        ]
        for key in _AI_KEYS:
            if key in all_models:
                ai_models.append(all_models[key])

        # 5. درآمد و تسویه من (Revenue & Payout)
        royalty_models = []
        _TEACHER_LABELS = {
            "TeacherWallet": "کیف پول من",
            "PayoutRequest": "درخواست تسویه",
            "TeacherBankAccount": "حساب بانکی (شبا)",
            "OrderAuthorRevenue": "درآمد از فروش",
            "WalletTransaction": "گردش حساب",
            "PoolBookShare": "سهم استخر اشتراک",
        }
        _ROYALTY_KEYS = [
            ("commerce", "TeacherWallet"),
            ("commerce", "PayoutRequest"),
            ("commerce", "TeacherBankAccount"),
            ("commerce", "OrderAuthorRevenue"),
            ("commerce", "WalletTransaction"),
            ("commerce", "PoolBookShare"),
        ]
        for key in _ROYALTY_KEYS:
            if key in all_models:
                m_dict = dict(all_models[key])
                obj_name = m_dict.get("object_name")
                if obj_name in _TEACHER_LABELS:
                    m_dict["name"] = _TEACHER_LABELS[obj_name]
                royalty_models.append(m_dict)

        teacher_apps = []
        if authoring_models:
            teacher_apps.append({
                "name": "میز تألیف و کتاب‌ها",
                "app_label": "catalog",
                "app_url": authoring_url,
                "has_module_perms": True,
                "models": authoring_models,
            })
        if royalty_models:
            commerce_app = next((a for a in raw_apps if a["app_label"] == "commerce"), None)
            commerce_url = commerce_app["app_url"] if commerce_app else reverse("admin:index")
            teacher_apps.append({
                "name": "درآمد و تسویه من",
                "app_label": "commerce_teacher",
                "app_url": commerce_url,
                "has_module_perms": True,
                "models": royalty_models,
            })
        if ai_models:
            teacher_apps.append({
                "name": "دستیار و هوش مصنوعی",
                "app_label": "catalog_ai",
                "app_url": authoring_url,
                "has_module_perms": True,
                "models": ai_models,
            })
        if teaching_models:
            teacher_apps.append({
                "name": "مدیریت کلاس‌ها و دوره‌ها",
                "app_label": "teacher_workflows",
                "app_url": teaching_url,
                "has_module_perms": True,
                "models": teaching_models,
            })
        if assessment_models:
            teacher_apps.append({
                "name": "ارزیابی، تمرین و بازخورد",
                "app_label": "learning",
                "app_url": assessment_url,
                "has_module_perms": True,
                "models": assessment_models,
            })

        return teacher_apps

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        workflow_models = []
        retained_apps = []

        _CATALOG_ORDER = {
            "Book": 1,
            "Section": 2,
            "Label": 3,
            "ChapterRevision": 4,
            "BookTeamTask": 5,
            "BookBoxMapping": 6,
            "BookOpinion": 7,
            "BookWaitlist": 8,
            "Major": 9,
            "Shelf": 10,
            "Banner": 11,
            "ShareSettings": 12,
            "FormulaCommand": 13,
            "AIProvider": 14,
            "BookAssistantAuditLog": 15,
            "BookChange": 16,
            "CleanupRun": 17,
        }

        for app in app_list:
            retained_models = []
            for model in app["models"]:
                if (app["app_label"], model["object_name"]) in _TEACHER_WORKFLOW_MODELS:
                    workflow_models.append(model)
                else:
                    retained_models.append(model)
            if retained_models:
                if app["app_label"] == "catalog":
                    retained_models.sort(
                        key=lambda model: (
                            _CATALOG_ORDER.get(model["object_name"], 50),
                            model["name"].casefold(),
                        )
                    )
                app["models"] = retained_models
                retained_apps.append(app)

        if workflow_models:
            # Custom ordering for teacher_workflows models: most frequently used first
            _WORKFLOW_ORDER = {
                "Classroom": 1,
                "ClassroomMember": 2,
                "PublicationRequest": 3,
                "BookAccessRequest": 4,
                "BookEditor": 5,
                "TeacherProfile": 6,
                "TeacherInvitation": 7,
                "TeacherApplication": 8,
            }
            workflow_models.sort(
                key=lambda model: (
                    _WORKFLOW_ORDER.get(model["object_name"], 50),
                    model["name"].casefold(),
                )
            )
            workflow_app = {
                "name": "اساتید و مؤلفان",
                "app_label": "teacher_workflows",
                "app_url": reverse("admin:index"),
                "has_module_perms": True,
                "models": workflow_models,
            }
            site_index = next(
                (index for index, app in enumerate(retained_apps) if app["app_label"] == "website"),
                None,
            )
            # Keep it next to «سایت», but as a separate peer in the admin navigation.
            insert_at = site_index + 1 if site_index is not None else len(retained_apps)
            retained_apps.insert(insert_at, workflow_app)

        # If a superuser has switched to teacher view mode, scope the navigation strictly to teacher's view
        user = getattr(request, "user", None)
        teacher_view_mode = False
        if request and hasattr(request, "session"):
            if "view" in request.GET:
                if request.GET.get("view") == "teacher":
                    request.session["admin_view_mode"] = "teacher"
                elif request.GET.get("view") == "admin":
                    request.session.pop("admin_view_mode", None)
            teacher_view_mode = (request.session.get("admin_view_mode") == "teacher")

        from apps.catalog.access import is_book_teacher

        # If user is a teacher OR a superuser previewing teacher view mode:
        is_teacher = bool(
            user and user.is_authenticated and (
                (user.is_superuser and teacher_view_mode) or (not user.is_superuser and is_book_teacher(user))
            )
        )

        if is_teacher:
            filtered_apps = []
            for app in retained_apps:
                app_models = [
                    m for m in app["models"]
                    if (app["app_label"], m["object_name"]) in _TEACHER_VISIBLE_MODELS
                ]
                if app_models:
                    app_copy = dict(app)
                    app_copy["models"] = app_models
                    filtered_apps.append(app_copy)
            return self._transform_teacher_app_list(filtered_apps)

        # If viewing as superuser (admin view), append real-time action counters to model names
        if user and user.is_authenticated and user.is_superuser and not teacher_view_mode:
            try:
                badges_map = getattr(request, "_limo_admin_badges", None) if request else None
                if badges_map is None:
                    from django.db.models import Count, IntegerField, Q, Subquery, Value
                    from django.db.models.functions import Coalesce
                    from django.utils import timezone
                    from apps.accounts.models import User
                    from apps.catalog.models import BookOpinion, BookTeamTask
                    from apps.commerce.models import Order, PayoutRequest
                    from apps.learning.models import Report
                    from apps.website.models import BookAccessRequest, PublicationRequest, TeacherApplication

                    today = timezone.localdate()
                    reports_qs = Report.objects.filter(status=Report.Status.OPEN)
                    pub_qs = PublicationRequest.objects.filter(
                        status__in=(PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO)
                    )
                    teacher_app_qs = TeacherApplication.objects.filter(status=TeacherApplication.Status.PENDING)
                    access_req_qs = BookAccessRequest.objects.filter(status=BookAccessRequest.Status.PENDING)
                    orders_qs = Order.objects.filter(status=Order.Status.PAID, paid_at__date=today)
                    payout_qs = PayoutRequest.objects.filter(
                        status__in=(PayoutRequest.Status.PENDING, PayoutRequest.Status.PROCESSING)
                    )
                    opinions_qs = BookOpinion.objects.filter(
                        Q(status=BookOpinion.Status.PENDING)
                        | Q(status=BookOpinion.Status.APPROVED, reported_at__isnull=False)
                    )
                    tasks_qs = BookTeamTask.objects.filter(is_done=False)

                    def _subcount(qs):
                        return Coalesce(
                            Subquery(
                                qs.order_by().annotate(_g=Value(1)).values("_g").annotate(_c=Count("*")).values("_c")[:1],
                                output_field=IntegerField(),
                            ),
                            Value(0),
                        )

                    counts = None
                    if getattr(user, "pk", None):
                        counts = (
                            User.objects.filter(pk=user.pk)
                            .values("pk")
                            .annotate(
                                reports_open=_subcount(reports_qs),
                                pub_pending=_subcount(pub_qs),
                                teacher_app_pending=_subcount(teacher_app_qs),
                                access_req_pending=_subcount(access_req_qs),
                                orders_today=_subcount(orders_qs),
                                payout_pending=_subcount(payout_qs),
                                opinions_pending=_subcount(opinions_qs),
                                open_team_tasks=_subcount(tasks_qs),
                            )
                            .first()
                        )
                    if counts is None:
                        counts = {
                            "reports_open": reports_qs.count(),
                            "pub_pending": pub_qs.count(),
                            "teacher_app_pending": teacher_app_qs.count(),
                            "access_req_pending": access_req_qs.count(),
                            "orders_today": orders_qs.count(),
                            "payout_pending": payout_qs.count(),
                            "opinions_pending": opinions_qs.count(),
                            "open_team_tasks": tasks_qs.count(),
                        }

                    badges_map = {
                        ("learning", "Report"): (counts["reports_open"], "lp-b-red", "گزارش‌های باز"),
                        ("teacher_workflows", "PublicationRequest"): (counts["pub_pending"], "lp-b-yellow", "در انتظار بررسی"),
                        ("teacher_workflows", "TeacherApplication"): (counts["teacher_app_pending"], "lp-b-yellow", "درخواست جدید"),
                        ("teacher_workflows", "BookAccessRequest"): (counts["access_req_pending"], "lp-b-blue", "درخواست باز"),
                        ("commerce", "Order"): (counts["orders_today"], "lp-b-green", "خرید امروز"),
                        ("commerce", "PayoutRequest"): (counts["payout_pending"], "lp-b-yellow", "درخواست تسویه باز"),
                        ("catalog", "BookOpinion"): (counts["opinions_pending"], "lp-b-yellow", "نظر نیازمند بازبینی یا گزارش‌شده"),
                        ("catalog", "BookTeamTask"): (counts["open_team_tasks"], "lp-b-yellow", "یادداشت‌های باز هماهنگی"),
                    }
                    if request is not None:
                        request._limo_admin_badges = badges_map

                from django.utils.html import format_html
                from apps.catalog.panel_display import fa_number

                for app in retained_apps:
                    for model in app.get("models", []):
                        key = (app.get("app_label"), model.get("object_name"))
                        if key in badges_map:
                            cnt, color_cls, title = badges_map[key]
                            if cnt > 0:
                                model["name"] = format_html(
                                    '{} <span class="lp-badge {} lp-menu-badge" title="{}">{}</span>',
                                    model["name"],
                                    color_cls,
                                    title,
                                    fa_number(cnt),
                                )
            except Exception:
                pass

        return retained_apps


class LimoAdminConfig(AdminConfig):
    default_site = "config.admin.LimoAdminSite"
