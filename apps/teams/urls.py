from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("", views.team_index, name="index"),
    path("coaches/", views.coach_index, name="coaches"),
    path("coaches/<int:pk>/", views.coach_detail, name="coach_detail"),
    path("<int:pk>/", views.team_detail, name="detail"),
    path("<int:team_id>/photos/add/", views.team_photo_add, name="photo_add"),
    path("<int:team_id>/photos/<int:photo_id>/feature/", views.team_photo_feature, name="photo_feature"),
    path("<int:team_id>/photos/<int:photo_id>/delete/", views.team_photo_delete, name="photo_delete"),
    path("players/<int:pk>/", views.player_detail, name="player_detail"),
]
