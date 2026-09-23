from django.urls import path

from . import views

app_name = "schedule"

urlpatterns = [
    path("", views.schedule_list, name="list"),
    # coach edit views go here later
]
