from django.urls import path

from . import views

urlpatterns = [
    path("", views.report_bug, name="report_bug"),
]
