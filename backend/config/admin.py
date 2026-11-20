"""Project admin site: keep teacher/editor workflows separate from public-site content."""

from django.contrib.admin.apps import AdminConfig
from django.contrib.admin.sites import AdminSite
from django.urls import reverse


_TEACHER_WORKFLOW_MODELS = frozenset({
    ("catalog", "BookEditor"),
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
    # learning
    ("learning", "Question"),
    ("learning", "Flashcard"),
    ("learning", "ExamSource"),
    ("learning", "Report"),
    # workflows
    ("teacher_workflows", "Classroom"),
    ("teacher_workflows", "ClassroomMember"),
    ("teacher_workflows", "PublicationRequest"),
})


class LimoAdminSite(AdminSite):
    """Group author, invitation, publication-review, and group-access workflows separately."""

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        workflow_models = []
        retained_apps = []

        _CATALOG_ORDER = {
            "Book": 1,
            "Section": 2,
            "Label": 3,
            "ChapterRevision": 4,
            "ShareSettings": 5,
            "Major": 6,
            "Shelf": 7,
            "Banner": 8,
            "FormulaCommand": 9,
            "BookWaitlist": 10,
            "BookChange": 11,
            "CleanupRun": 12,
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
                "TeacherInvitation": 6,
                "TeacherApplication": 7,
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
                teacher_view_mode = (request.GET.get("view") == "teacher")
            else:
                teacher_view_mode = (request.session.get("admin_view_mode") == "teacher")

        if user and user.is_authenticated and user.is_superuser and teacher_view_mode:
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
            return filtered_apps

        return retained_apps


class LimoAdminConfig(AdminConfig):
    default_site = "config.admin.LimoAdminSite"
