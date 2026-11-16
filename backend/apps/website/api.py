"""The app's «راهنما» and «قوانین» pages (edited in the panel: «صفحه‌های راهنما», «صفحه‌های سایت»)."""
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import HelpPage, SitePage


ORDER = {"terms": 0, "privacy": 1}


@api_view(["GET"])
@permission_classes([AllowAny])
def app_pages(request):
    """The lists for «حساب من»: help pages, and the site pages ticked «نمایش در اپ» with their last important change."""
    return Response(
        {
            "help": [{"id": h.id, "title": h.title} for h in HelpPage.objects.filter(is_hidden=False)],
            "pages": [
                {"slug": p.slug, "title": p.title, "updated_at": p.updated_at, "important_at": p.important_at}
                # «قوانین» first, then «حریم خصوصی», then the rest.
                for p in sorted(SitePage.objects.filter(show_in_app=True), key=lambda p: (ORDER.get(p.slug, 9), p.slug))
            ],
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def help_page(request, page_id):
    h = get_object_or_404(HelpPage, pk=page_id, is_hidden=False)
    return Response({"id": h.id, "title": h.title, "body": h.body, "updated_at": h.updated_at})


@api_view(["GET"])
@permission_classes([AllowAny])
def site_page(request, slug):
    # «قوانین» and «حریم خصوصی» are linked under the login button, so they open even when not listed in the app.
    p = get_object_or_404(SitePage, slug=slug)
    if not p.show_in_app and slug not in ("terms", "privacy"):
        raise Http404
    return Response({"slug": p.slug, "title": p.title, "body": p.body, "updated_at": p.updated_at, "important_at": p.important_at})
