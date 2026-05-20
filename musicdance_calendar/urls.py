from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from events.views import export_view, scrape_view

urlpatterns = [
    path("admin/events/export/", admin.site.admin_view(export_view), name="events_export"),
    path("admin/events/scrape/", admin.site.admin_view(scrape_view), name="events_scrape"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)