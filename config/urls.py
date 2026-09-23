from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("teams/", include("apps.teams.urls")),
    path("try-outs/", include("apps.tryouts.urls")),
    path("schedule/", include("apps.schedule.urls")),
    path("fees/", include("apps.fees.urls")),
]
