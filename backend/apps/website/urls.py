"""The website's pages. At the root of the site's own host (WEBSITE_HOSTS), and under /site/ elsewhere (to preview)."""
from django.urls import path

from . import applications, classroom_views, invitation_views, views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("join/<str:code>/", classroom_views.classroom_join, name="classroom-join"),
    path("verify-email/<str:token>/", classroom_views.verify_teacher_email, name="verify-teacher-email"),
    path("teacher-application/", applications.teacher_application, name="teacher-application"),
    path("teacher-invitation/", invitation_views.teacher_invitation, name="teacher-invitation"),
    path("books/", views.books, name="books"),
    path("books/<str:slug>/", views.book, name="book"),
    path("download/", views.download, name="download"),
    path("pricing/", views.pricing, name="pricing"),
    path("faq/", views.faq, name="faq"),
    path("p/<str:slug>/", views.page, name="page"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
