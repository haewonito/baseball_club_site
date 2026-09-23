from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard_redirect, name="dashboard"),
    path("dashboard/admin/", views.dashboard_admin, name="dashboard_admin"),
    path("dashboard/coach/", views.dashboard_coach, name="dashboard_coach"),
    path("dashboard/parent/", views.dashboard_parent, name="dashboard_parent"),
    path(
        "dashboard/parent/players/<int:player_id>/payments/",
        views.parent_player_payments,
        name="parent_player_payments",
    ),
    # invite claim views go here later
]
