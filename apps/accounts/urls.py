from django.contrib.auth.views import LogoutView
from django.urls import path, re_path

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
    path("dashboard/admin/schedule/", views.admin_schedule, name="admin_schedule"),
    path(
        "dashboard/admin/coaches/<int:user_id>/bio/",
        views.admin_coach_bio_edit,
        name="admin_coach_bio_edit",
    ),
    path(
        "dashboard/admin/tryout-posters/",
        views.admin_tryout_posters_list,
        name="admin_tryout_posters_list",
    ),
    path(
        "dashboard/admin/tryout-posters/add/",
        views.admin_tryout_poster_add,
        name="admin_tryout_poster_add",
    ),
    path(
        "dashboard/admin/tryout-posters/<int:pk>/edit/",
        views.admin_tryout_poster_edit,
        name="admin_tryout_poster_edit",
    ),
    path(
        "dashboard/admin/tryout-posters/<int:pk>/delete/",
        views.admin_tryout_poster_delete,
        name="admin_tryout_poster_delete",
    ),
    path("dashboard/coach/", views.dashboard_coach, name="dashboard_coach"),
    path("dashboard/coach/profile/", views.coach_profile_edit, name="coach_profile_edit"),
    path("dashboard/coach/tryouts/", views.coach_tryouts, name="coach_tryouts"),
    path("dashboard/tryouts/email/", views.tryout_mass_email, name="tryout_mass_email"),
    path(
        "dashboard/coach/tryouts/<int:pk>/decision/",
        views.coach_tryout_decision_change,
        name="coach_tryout_decision_change",
    ),
    path(
        "dashboard/coach/tryouts/<int:pk>/send-email/",
        views.coach_tryout_send_email,
        name="coach_tryout_send_email",
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
    re_path(
        r"^dashboard/coach/teams/(?P<team_id>\d+)/(?P<kind>practices|tournaments)/$",
        views.coach_events,
        name="coach_events",
    ),
    re_path(
        r"^dashboard/coach/teams/(?P<team_id>\d+)/(?P<kind>practices|tournaments)/add/$",
        views.coach_event_add,
        name="coach_event_add",
    ),
    re_path(
        r"^dashboard/coach/teams/(?P<team_id>\d+)/(?P<kind>practices|tournaments)/(?P<event_id>\d+)/edit/$",
        views.coach_event_edit,
        name="coach_event_edit",
    ),
    re_path(
        r"^dashboard/coach/teams/(?P<team_id>\d+)/(?P<kind>practices|tournaments)/(?P<event_id>\d+)/delete/$",
        views.coach_event_delete,
        name="coach_event_delete",
    ),
    path("dashboard/parent/", views.dashboard_parent, name="dashboard_parent"),
    path(
        "dashboard/parent/players/<int:player_id>/payments/",
        views.parent_player_payments,
        name="parent_player_payments",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/profile/",
        views.parent_player_profile_edit,
        name="parent_player_profile_edit",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/gallery/add/",
        views.parent_player_gallery_add,
        name="parent_player_gallery_add",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/gallery/<int:photo_id>/delete/",
        views.parent_player_gallery_delete,
        name="parent_player_gallery_delete",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/invite/",
        views.parent_invite_player,
        name="parent_invite_player",
    ),
    path(
        "dashboard/parent/players/<int:player_id>/invite/send-email/",
        views.parent_invite_send_email,
        name="parent_invite_send_email",
    ),
    path("invite/<uuid:token>/", views.invite_claim, name="invite_claim"),
]
