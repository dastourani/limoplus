from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.catalog import views as catalog
from apps.commerce import views as commerce
from apps.learning import views as learning
from apps.study import views as study

admin.site.site_header = "پنل مدیریت لیمو پلاس"
admin.site.site_title = "لیمو پلاس"
admin.site.index_title = "مدیریت"

api = [
    path("", include("apps.accounts.urls")),
    path("majors/", catalog.majors),
    path("majors/<slug:slug>/books/", catalog.major_books),
    path("books/<str:slug>/", catalog.book_detail),
    path("nodes/<int:node_id>/", catalog.node_detail),
    path("nodes/<int:node_id>/questions/", learning.node_questions),
    path("nodes/<int:node_id>/flashcards/", learning.node_flashcards),
    path("questions/<int:question_id>/answer/", learning.answer),
    path("banners/", catalog.banners),
    path("banners/<int:banner_id>/click/", catalog.banner_click),
    # The learner's own data
    path("nodes/<int:node_id>/me/", study.node_state),
    path("nodes/<int:node_id>/progress/", study.save_progress),
    path("nodes/<int:node_id>/bookmark/", study.toggle_bookmark),
    path("nodes/<int:node_id>/notes/", study.add_note),
    path("notes/<int:note_id>/", study.edit_note),
    path("nodes/<int:node_id>/practice/", study.practice_state),
    path("nodes/<int:node_id>/practice/reset/", study.practice_reset),
    path("nodes/<int:node_id>/flashcards/me/", study.flashcard_state),
    path("flashcards/<int:flashcard_id>/review/", study.review_flashcard),
    path("questions/<int:question_id>/report/", study.report_question),
    path("flashcards/<int:flashcard_id>/report/", study.report_flashcard),
    path("nodes/<int:node_id>/report/", study.report_node),
    path("nodes/<int:node_id>/exams/", study.start_exam),
    path("exams/<int:attempt_id>/", study.exam_detail),
    path("exams/<int:attempt_id>/submit/", study.submit_exam),
    path("me/exams/", study.my_exams),
    path("me/library/", study.library),
    path("me/stats/", study.stats),
    path("books/<str:slug>/offline/", study.offline_bundle),
    # Sales
    path("offers/", commerce.offers),
    path("plans/", commerce.plans),
    path("orders/", commerce.create_order),
    path("orders/<int:order_id>/", commerce.order_status),
    path("me/purchases/", commerce.my_purchases),
    path("payments/zibal/callback/", commerce.zibal_callback),
]

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(api)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
