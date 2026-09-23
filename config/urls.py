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
