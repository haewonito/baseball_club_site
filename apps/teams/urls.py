from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("", views.team_index, name="index"),
    path("coaches/", views.coach_index, name="coaches"),
    path("<int:pk>/", views.team_detail, name="detail"),
]
