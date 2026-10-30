from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.catalog import views as catalog
from apps.learning import views as learning

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
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
