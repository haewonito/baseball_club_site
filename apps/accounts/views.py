from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.fees.models import Payment
from apps.schedule.models import Event, EventType
from apps.teams.models import Team, TeamCoach
from apps.tryouts.models import TryoutSignup, TryoutStatus, TryoutStatusChange

from .forms import PlayerRosterForm, PracticeEventForm
from .models import ParentPlayerLink, Player


class LoginView(BaseLoginView):
    template_name = "accounts/login.html"


@login_required
def dashboard_redirect(request):
    """
    Single landing point after login. Priority when a user holds more than
    one role (e.g. the league owner, who is both Admin and Coach) is
    admin > coach > parent -- Admin is the most privileged view.
    """
    user = request.user
    if user.is_admin:
        return redirect("accounts:dashboard_admin")
    if user.is_coach:
        return redirect("accounts:dashboard_coach")
    if user.is_parent:
        return redirect("accounts:dashboard_parent")
    if user.is_superuser:
        return redirect("/admin/")
    return render(request, "accounts/no_dashboard.html")


@login_required
def dashboard_admin(request):
    if not request.user.is_admin:
        raise PermissionDenied
    return render(request, "accounts/dashboard_admin.html")


@login_required
def admin_tryouts_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    signups = TryoutSignup.objects.prefetch_related("positions").order_by("-submitted_at")
    years = list(
        TryoutSignup.objects.order_by("-tryout_year").values_list("tryout_year", flat=True).distinct()
    )
    selected_year = request.GET.get("year", "")
    if selected_year:
        signups = signups.filter(tryout_year=selected_year)

    return render(
        request,
        "accounts/admin_tryouts_list.html",
        {
            "signups": signups,
            "years": years,
            "selected_year": selected_year,
            "status_choices": TryoutStatus.choices,
        },
    )


@login_required
def admin_tryout_detail(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    signup = get_object_or_404(TryoutSignup.objects.prefetch_related("positions"), pk=pk)
    status_changes = signup.status_changes.select_related("changed_by").order_by("-changed_at")

    return render(
        request,
        "accounts/admin_tryout_detail.html",
        {
            "signup": signup,
            "status_choices": TryoutStatus.choices,
            "status_changes": status_changes,
        },
    )


@login_required
@require_POST
def admin_tryout_status_change(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    signup = get_object_or_404(TryoutSignup, pk=pk)
    new_status = request.POST.get("status", "")
    if new_status not in dict(TryoutStatus.choices):
        return HttpResponseBadRequest("Invalid status")

    if new_status != signup.status:
        TryoutStatusChange.objects.create(
            signup=signup,
            old_status=signup.status,
            new_status=new_status,
            changed_by=request.user,
        )
        signup.status = new_status
        signup.save(update_fields=["status"])

    return render(
        request,
        "partials/_tryout_status_select.html",
        {"signup": signup, "status_choices": TryoutStatus.choices},
    )


def _get_coach_team_or_404(user, team_id):
    return get_object_or_404(Team, pk=team_id, coach_assignments__coach=user)


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
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    players = team.players.prefetch_related("positions").order_by("last_name", "first_name")
    return render(request, "accounts/coach_roster.html", {"team": team, "players": players})


@login_required
def coach_roster_add(request, team_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
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
def coach_roster_edit_player(request, team_id, player_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    player = get_object_or_404(Player, pk=player_id, team=team)
    if request.method == "POST":
        form = PlayerRosterForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            return redirect("accounts:coach_roster", team_id=team.pk)
    else:
        form = PlayerRosterForm(instance=player)
    return render(
        request,
        "accounts/coach_roster_form.html",
        {"team": team, "form": form, "heading": f"Edit {player}"},
    )


@login_required
@require_POST
def coach_roster_remove_player(request, team_id, player_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    player = get_object_or_404(Player, pk=player_id, team=team)
    # Removes from this roster, doesn't delete the Player -- preserves fee
    # history and keeps the record around for reassignment elsewhere.
    player.team = None
    player.save()
    return redirect("accounts:coach_roster", team_id=team.pk)


@login_required
def coach_practices(request, team_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    events = team.events.filter(event_type=EventType.PRACTICE).order_by("start_datetime")
    return render(request, "accounts/coach_practices.html", {"team": team, "events": events})


@login_required
def coach_practice_add(request, team_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    if request.method == "POST":
        form = PracticeEventForm(
            request.POST, instance=Event(team=team, event_type=EventType.PRACTICE)
        )
        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.save()
            return redirect("accounts:coach_practices", team_id=team.pk)
    else:
        form = PracticeEventForm()
    return render(
        request,
        "accounts/coach_practice_form.html",
        {"team": team, "form": form, "heading": "Add Practice"},
    )


@login_required
def coach_practice_edit(request, team_id, event_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    event = get_object_or_404(Event, pk=event_id, team=team, event_type=EventType.PRACTICE)
    if request.method == "POST":
        form = PracticeEventForm(request.POST, instance=event)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            return redirect("accounts:coach_practices", team_id=team.pk)
    else:
        form = PracticeEventForm(instance=event)
    return render(
        request,
        "accounts/coach_practice_form.html",
        {"team": team, "form": form, "heading": "Edit Practice"},
    )


@login_required
@require_POST
def coach_practice_delete(request, team_id, event_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    event = get_object_or_404(Event, pk=event_id, team=team, event_type=EventType.PRACTICE)
    event.delete()
    return redirect("accounts:coach_practices", team_id=team.pk)


@login_required
def coach_tournaments(request, team_id):
    if not request.user.is_coach:
        raise PermissionDenied
    team = _get_coach_team_or_404(request.user, team_id)
    events = team.events.filter(event_type=EventType.TOURNAMENT).order_by("start_datetime")
    return render(request, "accounts/coach_tournaments.html", {"team": team, "events": events})


@login_required
def coach_tryouts(request):
    if not request.user.is_coach:
        raise PermissionDenied
    signups = TryoutSignup.objects.prefetch_related("positions").order_by("-submitted_at")
    return render(request, "accounts/coach_tryouts.html", {"signups": signups})


@login_required
def dashboard_parent(request):
    if not request.user.is_parent:
        raise PermissionDenied

    links = (
        ParentPlayerLink.objects.filter(parent=request.user, removed_at__isnull=True)
        .select_related("player", "player__team")
        .prefetch_related("player__fees__payments")
    )
    now = timezone.now()
    cards = []
    for link in links:
        player = link.player
        next_event = None
        if player.team:
            next_event = player.team.events.filter(start_datetime__gte=now).order_by("start_datetime").first()
        # Team-wide fees (Fee.player=None) aren't included here -- per
        # CLAUDE.md that's an open design question, not yet resolved.
        balance = sum(fee.balance for fee in player.fees.all())
        cards.append({"player": player, "next_event": next_event, "balance": balance})

    return render(request, "accounts/dashboard_parent.html", {"cards": cards})


@login_required
def parent_player_payments(request, player_id):
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player
    fees = list(player.fees.all())
    total_due = sum(fee.amount_due for fee in fees)

    payments = Payment.objects.filter(fee__player=player).select_related("fee").order_by("paid_at", "recorded_at")
    running_total = 0
    rows = []
    for payment in payments:
        running_total += payment.amount
        rows.append({"payment": payment, "running_total": running_total})

    return render(
        request,
        "accounts/parent_player_payments.html",
        {
            "player": player,
            "rows": rows,
            "total_due": total_due,
            "total_paid": running_total,
            "balance": total_due - running_total,
        },
    )
