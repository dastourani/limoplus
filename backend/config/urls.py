import re

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from apps.accounts import views as accounts_views
from apps.accounts.admin_login import admin_login
from apps.catalog import search as catalog_search
from apps.catalog import views as catalog
from apps.commerce import views as commerce
from apps.guard import views as guard
from apps.learning import views as learning
from apps.releases import views as releases
from apps.study import mistakes
from apps.study import reviews
from apps.study import time as study_time
from apps.study import views as study
from apps.website import api as website_api

admin.site.site_header = "پنل مدیریت لیموخوان"
admin.site.site_title = "لیموخوان"
admin.site.index_title = "مدیریت"

api = [
    path("", include("apps.accounts.urls")),
    path("majors/", catalog.majors),
    path("shelves/", catalog.shelves),
    path("majors/<slug:slug>/books/", catalog.major_books),
    path("books/", catalog.all_books),
    path("search/", catalog_search.search),
    path("books/<str:slug>/", catalog.book_detail),
    path("books/<str:slug>/glossary/", catalog.book_glossary),
    path("books/<str:slug>/samples/", learning.book_samples),
    path("books/<str:slug>/past/", learning.book_past_exams),
    path("books/<str:slug>/past/questions/", learning.book_past_questions),
    path("books/<str:slug>/past/repeats/", learning.book_past_repeats),
    path("books/<str:slug>/notify/", catalog.book_notify),
    path("books/<str:slug>/reviews/", catalog.submit_book_review),
    path("books/<str:slug>/changes/", catalog.book_changes),
    path("formula-commands/", catalog.formula_commands),
    path("nodes/<int:node_id>/", catalog.node_detail),
    path("nodes/<int:node_id>/questions/", learning.node_questions),
    path("nodes/<int:node_id>/boxes/", catalog.node_boxes),
    path("nodes/<int:node_id>/flashcards/", learning.node_flashcards),
    path("questions/<int:question_id>/answer/", learning.answer),
    path("app/version/", releases.app_version),
    path("api/releases/sync-github/", releases.sync_github_webhook),
    path("app/pages/", website_api.app_pages),
    path("app/pages/<str:slug>/", website_api.site_page),
    path("app/help/<int:page_id>/", website_api.help_page),
    path("banners/", catalog.banners),
    path("banners/<int:banner_id>/click/", catalog.banner_click),
    # The learner's own data
    path("nodes/<int:node_id>/me/", study.node_state),
    path("nodes/<int:node_id>/progress/", study.save_progress),
    path("nodes/<int:node_id>/bookmark/", study.toggle_bookmark),
    path("nodes/<int:node_id>/notes/", study.add_note),
    path("nodes/<int:node_id>/copy/", guard.copy_text),
    path("copy/quota/", guard.copy_quota),
    path("notes/<int:note_id>/", study.edit_note),
    path("nodes/<int:node_id>/practice/", study.practice_state),
    path("nodes/<int:node_id>/practice/reset/", study.practice_reset),
    path("nodes/<int:node_id>/flashcards/me/", study.flashcard_state),
    path("flashcards/<int:flashcard_id>/review/", study.review_flashcard),
    path("questions/<int:question_id>/report/", study.report_question),
    path("flashcards/<int:flashcard_id>/report/", study.report_flashcard),
    path("nodes/<int:node_id>/report/", study.report_node),
    path("me/reports/fixed/", study.reports_fixed),
    path("nodes/<int:node_id>/exams/", study.start_exam),
    path("nodes/<int:node_id>/exam-info/", study.exam_info),
    path("exams/<int:attempt_id>/", study.exam_detail),
    path("exams/<int:attempt_id>/submit/", study.submit_exam),
    path("me/exams/", study.my_exams),
    path("me/mistakes/", mistakes.my_mistakes),
    path("me/today/", mistakes.today),
    path("me/reviews/", reviews.my_reviews),
    path("me/time/", study_time.add_time),
    path("me/reviews/start/", reviews.start_review),
    path("me/reviews/<int:session_id>/", reviews.review_session),
    path("me/reviews/<int:session_id>/more/", reviews.review_more),
    path("me/reviews/<int:session_id>/finish/", reviews.finish_review),
    path("nodes/<int:node_id>/finish/", reviews.finish_chapter),
    path("me/quick/", mistakes.quick),
    path("me/mistakes/questions/", mistakes.mistake_questions),
    path("me/mistakes/<int:question_id>/reason/", mistakes.mistake_reason),
    path("me/flashcards/due/", study.due_flashcards),
    path("me/library/reorder/", study.reorder_library),
    path("me/library/books/<int:book_id>/", study.library_book),
    path("me/library/", study.library),
    path("me/stats/", study.stats),
    path("books/<str:slug>/offline/", study.offline_bundle),
    path("books/<str:slug>/words/me/", study.known_words),
    # Sales
    path("offers/", commerce.offers),
    path("plans/", commerce.plans),
    path("orders/", commerce.create_order),
    path("orders/<int:order_id>/", commerce.order_status),
    path("me/purchases/", commerce.my_purchases),
    path("payments/zibal/callback/", commerce.zibal_callback),
]

from apps.website.classroom_views import classroom_join, verify_teacher_email

# The same on every host (config/website_urls.py uses them too).
shared = [
    path("join/<str:code>/", classroom_join, name="root-classroom-join"),
    path("verify-email/<str:token>/", verify_teacher_email, name="root-verify-teacher-email"),
    path(f"{settings.ADMIN_URL}open-app/", accounts_views.open_app, name="panel-open-app"),
    # Shadow Django's password form with the OTP-first panel login; the break-glass password is superuser-only.
    path(f"{settings.ADMIN_URL}login/", admin_login, name="admin-login"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(api)),
]

if settings.DEBUG:
    shared += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    # No nginx in front (e.g. ParsPack PaaS): Django serves the uploaded files itself.
    from django.views.static import serve

    shared += [re_path(rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]

# The website (apps/website): here under /site/; at the root on its own host (WEBSITE_HOSTS).
urlpatterns = [*shared, path("site/", include("apps.website.urls"))]

# The web version of the app at the root (anything not matched above), when WEBAPP_DIR holds a build.
from apps.catalog.webapp import webapp  # noqa: E402


# Not for the API, the panel, static files or media (so «/admin» still gets its slash added, and so on).
_reserved = "|".join(re.escape(x.strip("/")) for x in ("api", "static", "media", "site", "join", "verify-email", settings.ADMIN_URL) if x.strip("/"))
urlpatterns += [re_path(rf"^(?!(?:{_reserved})(?:/|$))(?P<path>.*)$", webapp)]
