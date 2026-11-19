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


class LimoAdminSite(AdminSite):
    """Group author, invitation, publication-review, and group-access workflows separately."""

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        workflow_models = []
        retained_apps = []

        for app in app_list:
            retained_models = []
            for model in app["models"]:
                if (app["app_label"], model["object_name"]) in _TEACHER_WORKFLOW_MODELS:
                    workflow_models.append(model)
                else:
                    retained_models.append(model)
            if retained_models:
                app["models"] = retained_models
                retained_apps.append(app)

        if workflow_models:
            workflow_models.sort(key=lambda model: model["name"].casefold())
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

        return retained_apps


class LimoAdminConfig(AdminConfig):
    default_site = "config.admin.LimoAdminSite"
