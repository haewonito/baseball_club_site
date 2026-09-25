from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard_redirect, name="dashboard"),
    path("dashboard/admin/", views.dashboard_admin, name="dashboard_admin"),
    path("dashboard/admin/tryouts/", views.admin_tryouts_list, name="admin_tryouts_list"),
    path("dashboard/admin/tryouts/<int:pk>/", views.admin_tryout_detail, name="admin_tryout_detail"),
    path(
        "dashboard/admin/tryouts/<int:pk>/status/",
        views.admin_tryout_status_change,
        name="admin_tryout_status_change",
    ),
    path(
        "dashboard/admin/tryouts/<int:pk>/response-invite/",
        views.admin_tryout_response_invite,
        name="admin_tryout_response_invite",
    ),
    path(
        "dashboard/admin/tryouts/<int:pk>/promote/",
        views.admin_tryout_promote,
        name="admin_tryout_promote",
    ),
    path("dashboard/admin/fees/", views.admin_fees_list, name="admin_fees_list"),
    path("dashboard/admin/fees/add/", views.admin_fee_add, name="admin_fee_add"),
    path("dashboard/admin/fees/<int:pk>/", views.admin_fee_detail, name="admin_fee_detail"),
    path("dashboard/admin/fees/<int:pk>/edit/", views.admin_fee_edit, name="admin_fee_edit"),
    path(
        "dashboard/admin/fees/<int:pk>/payments/add/",
        views.admin_fee_record_payment,
        name="admin_fee_record_payment",
    ),
    path("dashboard/admin/coaches/", views.admin_coaches_list, name="admin_coaches_list"),
    path(
        "dashboard/admin/coaches/<int:user_id>/bio/",
        views.admin_coach_bio_edit,
        name="admin_coach_bio_edit",
    ),
    path("dashboard/coach/", views.dashboard_coach, name="dashboard_coach"),
    path("dashboard/coach/tryouts/", views.coach_tryouts, name="coach_tryouts"),
    path(
        "dashboard/coach/tryouts/<int:pk>/decision/",
        views.coach_tryout_decision_change,
        name="coach_tryout_decision_change",
    ),
    path("dashboard/coach/teams/<int:team_id>/roster/", views.coach_roster, name="coach_roster"),
    path(
        "dashboard/coach/teams/<int:team_id>/roster/add/",
        views.coach_roster_add,
        name="coach_roster_add",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/roster/players/<int:player_id>/edit/",
        views.coach_roster_edit_player,
        name="coach_roster_edit_player",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/roster/players/<int:player_id>/remove/",
        views.coach_roster_remove_player,
        name="coach_roster_remove_player",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/roster/bulk-move/",
        views.coach_roster_bulk_move,
        name="coach_roster_bulk_move",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/practices/",
        views.coach_practices,
        name="coach_practices",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/practices/add/",
        views.coach_practice_add,
        name="coach_practice_add",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/practices/<int:event_id>/edit/",
        views.coach_practice_edit,
        name="coach_practice_edit",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/practices/<int:event_id>/delete/",
        views.coach_practice_delete,
        name="coach_practice_delete",
    ),
    path(
        "dashboard/coach/teams/<int:team_id>/tournaments/",
        views.coach_tournaments,
        name="coach_tournaments",
    ),
    path("dashboard/parent/", views.dashboard_parent, name="dashboard_parent"),
    path(
        "dashboard/parent/players/<int:player_id>/payments/",
        views.parent_player_payments,
        name="parent_player_payments",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/invite/",
        views.parent_invite_player,
        name="parent_invite_player",
    ),
    path("invite/<uuid:token>/", views.invite_claim, name="invite_claim"),
]
