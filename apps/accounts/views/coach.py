
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.schedule.models import Event, EventType
from apps.teams.models import Team, TeamCoach

from ..forms import EventForm, SyncedEventForm, PlayerRosterForm
from ..models import Player
from .common import _get_roster_team_or_404


@login_required
def dashboard_coach(request):
    if not request.user.is_coach:
        raise PermissionDenied

    assignments = list(
        TeamCoach.objects.filter(coach=request.user).select_related("team").order_by("team__name")
    )
    current_assignment = None
    if assignments:
        team_id = request.GET.get("team")
        current_assignment = next(
            (a for a in assignments if str(a.team_id) == team_id), assignments[0]
        )

    return render(
        request,
        "accounts/dashboard_coach.html",
        {
            "assignments": assignments,
            "current_assignment": current_assignment,
            "current_team": current_assignment.team if current_assignment else None,
        },
    )


@login_required
def coach_roster(request, team_id):
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    team = _get_roster_team_or_404(request.user, team_id)
    players = team.players.prefetch_related("positions").order_by("last_name", "first_name")
    # Destination options for the bulk "move to team" action below -- every
    # other team, not just public ones, since the age-up case is moving
    # players onto a newly pre-created team that isn't public yet.
    other_teams = Team.objects.exclude(pk=team.pk).filter(is_deleted_placeholder=False).order_by("-season_year", "name")
    return render(
        request,
        "accounts/coach_roster.html",
        {"team": team, "players": players, "other_teams": other_teams},
    )


@login_required
def coach_roster_add(request, team_id):
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    team = _get_roster_team_or_404(request.user, team_id)
    if request.method == "POST":
        form = PlayerRosterForm(request.POST, instance=Player(team=team))
        if form.is_valid():
            form.save()
            return redirect("accounts:coach_roster", team_id=team.pk)
    else:
        form = PlayerRosterForm()
    return render(
        request,
        "accounts/coach_roster_form.html",
        {"team": team, "form": form, "heading": "Add Player"},
    )


@login_required
@require_POST
def coach_roster_remove_player(request, team_id, player_id):
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    team = _get_roster_team_or_404(request.user, team_id)
    player = get_object_or_404(Player, pk=player_id, team=team)
    # Removes from this roster, doesn't delete the Player -- preserves fee
    # history and keeps the record around for reassignment elsewhere.
    player.team = None
    player.save()
    return redirect("accounts:coach_roster", team_id=team.pk)


@login_required
@require_POST
def coach_roster_bulk_move(request, team_id):
    """
    Age-up promotion (roster-promotion plan step 8): move a checked batch of
    existing players from this team onto another team in one action.
    PlayerPosition rows carry over automatically -- they key off the
    player, not the team, so reassigning Player.team doesn't touch them.
    """
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    team = _get_roster_team_or_404(request.user, team_id)

    player_ids = request.POST.getlist("player_ids")
    destination_id = request.POST.get("destination_team")
    if not player_ids or not destination_id:
        messages.error(request, "Select at least one player and a destination team.")
        return redirect("accounts:coach_roster", team_id=team.pk)

    destination = get_object_or_404(Team, pk=destination_id)
    moved = Player.objects.filter(pk__in=player_ids, team=team).update(team=destination)
    messages.success(request, f"Moved {moved} player(s) to {destination.name}.")
    return redirect("accounts:coach_roster", team_id=team.pk)


# URL `kind` segment -> Event.event_type. Coaches manage all kinds for
# their own team(s); admins for any team (same scoping as the roster).
EVENT_KINDS = {
    "practices": EventType.PRACTICE,
    "tournaments": EventType.TOURNAMENT,
    "events": EventType.EVENT,
}


def _get_event_team_or_404(request, team_id):
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    return _get_roster_team_or_404(request.user, team_id)


def _event_next_url(request):
    # Set when the add/edit link came from the public team page, so saving
    # returns there instead of to this list. The form posts back to its own
    # URL (query string included), so this reads the same on GET and POST.
    next_url = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


def _event_back_url(user, team):
    # An admin who isn't on this team's staff came from the admin Schedule
    # page -- the coach dashboard wouldn't show them this team.
    if TeamCoach.objects.filter(coach=user, team=team).exists():
        return f"{reverse('accounts:dashboard_coach')}?team={team.pk}"
    return reverse("accounts:admin_schedule")


@login_required
def coach_events(request, team_id, kind):
    team = _get_event_team_or_404(request, team_id)
    event_type = EVENT_KINDS[kind]
    events = team.events.filter(event_type=event_type).order_by("start_datetime")
    return render(
        request,
        "accounts/coach_events.html",
        {
            "team": team,
            "events": events,
            "kind": kind,
            "event_type_label": event_type.label,
            "back_url": _event_back_url(request.user, team),
        },
    )


@login_required
def coach_event_add(request, team_id, kind):
    team = _get_event_team_or_404(request, team_id)
    event_type = EVENT_KINDS[kind]
    if request.method == "POST":
        form = EventForm(request.POST, instance=Event(team=team, event_type=event_type))
        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.save()
            return redirect(
                _event_next_url(request) or reverse("accounts:coach_events", args=[team.pk, kind])
            )
    else:
        form = EventForm(instance=Event(team=team, event_type=event_type))
    return render(
        request,
        "accounts/coach_event_form.html",
        {
            "team": team,
            "form": form,
            "kind": kind,
            "has_feed": bool(team.gamechanger_feed_url),
            "heading": f"Add {event_type.label}",
            "next_url": _event_next_url(request),
        },
    )


@login_required
def coach_event_edit(request, team_id, kind, event_id):
    team = _get_event_team_or_404(request, team_id)
    event_type = EVENT_KINDS[kind]
    event = get_object_or_404(Event, pk=event_id, team=team, event_type=event_type)
    if request.method == "POST":
        form = (SyncedEventForm if event.is_synced else EventForm)(request.POST, instance=event)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            return redirect(
                _event_next_url(request) or reverse("accounts:coach_events", args=[team.pk, kind])
            )
    else:
        form = (SyncedEventForm if event.is_synced else EventForm)(instance=event)
    return render(
        request,
        "accounts/coach_event_form.html",
        {
            "team": team,
            "form": form,
            "kind": kind,
            "event": event,
            "heading": f"Edit {event_type.label}",
            "next_url": _event_next_url(request),
        },
    )


@login_required
@require_POST
def coach_event_delete(request, team_id, kind, event_id):
    team = _get_event_team_or_404(request, team_id)
    event = get_object_or_404(Event, pk=event_id, team=team, event_type=EVENT_KINDS[kind])
    if event.is_synced:
        # GameChanger owns these; deleting one would just bring it back on
        # the next sync. Cancel it instead (edit -> status).
        messages.error(
            request,
            "That event comes from GameChanger and can't be deleted here. "
            "Edit it and set its status to Cancelled instead.",
        )
        return redirect("accounts:coach_events", team_id=team.pk, kind=kind)
    event.delete()
    return redirect("accounts:coach_events", team_id=team.pk, kind=kind)
