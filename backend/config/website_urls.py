"""URLs for the website's own host (see apps.website.middleware): the site at the root, plus the API, the panel,
static files and media as everywhere else, but no web app."""
from django.urls import include, path

from config.urls import shared

urlpatterns = [*shared, path("", include("apps.website.urls"))]
