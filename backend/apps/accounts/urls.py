from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("auth/request-otp/", views.request_otp, name="request-otp"),
    path("auth/verify-otp/", views.verify_otp, name="verify-otp"),
    path("auth/logout/", views.logout, name="logout"),
    path("me/", views.me, name="me"),
    path("me/sessions/", views.sessions, name="sessions"),
    path("me/sessions/<int:session_id>/revoke/", views.revoke_session, name="revoke-session"),
]
