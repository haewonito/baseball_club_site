from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("", views.team_index, name="index"),
    path("coaches/", views.coach_index, name="coaches"),
    path("coaches/<int:pk>/", views.coach_detail, name="coach_detail"),
    path("<int:pk>/", views.team_detail, name="detail"),
]
