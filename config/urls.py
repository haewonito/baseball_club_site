from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("teams/", include("apps.teams.urls")),
    path("try-outs/", include("apps.tryouts.urls")),
    path("schedule/", include("apps.schedule.urls")),
    path("fees/", include("apps.fees.urls")),
]

if not settings.USE_R2:
    # Local dev only -- uploads write to ./media (see USE_R2 in settings.py),
    # so they need Django's own dev-server static helper to be reachable.
    # In production USE_R2=True and R2 serves the file directly, and this
    # helper is also a no-op whenever DEBUG=False regardless.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
