import logging

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.fees.models import FEE_STATUS_LABELS, Fee, Payment
from apps.schedule.models import Event, EventType
from apps.teams.models import CoachProfile, PlayerPosition, Team, TeamCoach
from apps.tryouts.emails import (
    MassEmailError,
    send_response_invite_email,
    send_tryout_mass_email,
)
from apps.tryouts.roster import find_existing_player, promote_signup_to_roster
from apps.tryouts.models import (
    TryoutDecision,
    TryoutDecisionChange,
    TryoutFamilyResponse,
    TryoutMassEmail,
    TryoutPoster,
    TryoutResponseInvite,
    TryoutSignup,
)

from .emails import send_parent_invite_email
from .forms import (
    CoachProfileForm,
    EventForm,
    SyncedEventForm,
    FeeForm,
    InviteClaimSignupForm,
    ParentInviteEmailForm,
    PaymentForm,
    PlayerGalleryPhotoForm,
    PlayerProfileForm,
    PlayerRosterForm,
    TryoutMassEmailForm,
    TryoutPosterForm,
    downsize_image,
)
from .models import (
    MAX_LINKED_ADULTS_PER_PLAYER,
    ParentInvite,
    ParentPlayerLink,
    Player,
    PlayerGalleryPhoto,
    Role,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)


class LoginView(BaseLoginView):
    template_name = "accounts/login.html"

    def get_initial(self):
        # ?email= prefills the email box (the try-out sign-up form's
        # "log in first" prompt sends it).
        initial = super().get_initial()
        if self.request.method == "GET" and self.request.GET.get("email"):
            initial["username"] = self.request.GET["email"]
        return initial


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

    signups = (
        TryoutSignup.objects.select_related("team", "promoted_player")
        .prefetch_related("positions")
        .order_by("player_last_name", "player_first_name")
    )
    years = [
        (year, f"{year - 1}-{year}")
        for year in TryoutSignup.objects.filter(team__is_deleted_placeholder=False)
        .order_by("-team__season_year")
        .values_list("team__season_year", flat=True)
        .distinct()
    ]
    selected_year = request.GET.get("year", "")
    if selected_year:
        signups = signups.filter(team__season_year=selected_year)

    return render(
        request,
        "accounts/admin_tryouts_list.html",
        {
            "signups": signups,
            "years": years,
            "selected_year": selected_year,
            "decision_choices": TryoutDecision.choices,
        },
    )


@login_required
def admin_tryout_detail(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    signup = get_object_or_404(
        TryoutSignup.objects.select_related("team", "promoted_player").prefetch_related(
            "positions"
        ),
        pk=pk,
    )
    decision_changes = signup.decision_changes.select_related("changed_by").order_by("-changed_at")
    existing_player = None
    if not signup.promoted_player_id:
        existing_player = find_existing_player(signup, signup.responded_by)

    return render(
        request,
        "accounts/admin_tryout_detail.html",
        {
            "signup": signup,
            "existing_player": existing_player,
            "decision_choices": TryoutDecision.choices,
            "decision_changes": decision_changes,
        },
    )


@login_required
@require_POST
def admin_tryout_promote(request, pk):
    """
    Manual fallback for promote_signup_to_roster -- accepting normally
    promotes automatically, but not when the sign-up had no date of birth
    (add it via Django admin, then use this).
    """
    if not request.user.is_admin:
        raise PermissionDenied

    signup = get_object_or_404(
        TryoutSignup.objects.select_related("team", "responded_by").prefetch_related("positions"),
        pk=pk,
    )
    if signup.family_response != TryoutFamilyResponse.ACCEPTED:
        raise PermissionDenied
    if signup.promoted_player_id:
        return redirect("accounts:admin_tryout_detail", pk=signup.pk)
    if signup.team.is_deleted_placeholder:
        messages.error(request, "Can't promote -- the team this sign-up was for was deleted.")
        return redirect("accounts:admin_tryout_detail", pk=signup.pk)

    # "yes" = the admin confirmed this is the returning player the
    # detail page flagged; move that Player instead of creating another.
    existing_player = None
    if request.POST.get("returning") == "yes":
        existing_player = find_existing_player(signup, signup.responded_by)
    if existing_player is None and not signup.date_of_birth:
        messages.error(request, "Can't promote -- this sign-up is missing a date of birth.")
        return redirect("accounts:admin_tryout_detail", pk=signup.pk)

    player = promote_signup_to_roster(
        signup, created_by=request.user, existing_player=existing_player
    )
    if not signup.responded_by_id:
        messages.warning(
            request,
            f"{player} was added, but no parent account was recorded for this sign-up -- "
            "link one manually via the Django admin's Parent Player Links.",
        )

    if existing_player is not None:
        messages.success(request, f"{player} (returning player) moved to {signup.team.name}'s roster.")
    else:
        messages.success(request, f'{player} added to {signup.team.name}\'s roster.')
    return redirect("accounts:admin_tryout_detail", pk=signup.pk)


@login_required
def admin_fees_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    only_outstanding = request.GET.get("outstanding") == "1"
    fees = (
        Fee.objects.select_related("player", "team", "reminder")
        .prefetch_related("payments")
        .order_by("-created_at")
    )

    rows = []
    total_outstanding = 0
    for fee in fees:
        balance = fee.balance
        if balance > 0:
            total_outstanding += balance
        if only_outstanding and balance <= 0:
            continue
        status = fee.status
        rows.append(
            {
                "fee": fee,
                "balance": balance,
                "status_label": FEE_STATUS_LABELS.get(status, status),
            }
        )

    return render(
        request,
        "accounts/admin_fees_list.html",
        {"rows": rows, "total_outstanding": total_outstanding, "only_outstanding": only_outstanding},
    )


@login_required
def admin_fee_add(request):
    if not request.user.is_admin:
        raise PermissionDenied

    if request.method == "POST":
        form = FeeForm(request.POST)
        if form.is_valid():
            team = form.cleaned_data["team"]
            if team:
                # Team-wide is per-player, full amount each -- not a single
                # shared row and not split. Fans out here, at creation
                # time, into ordinary per-player Fees indistinguishable
                # from one added directly for a single kid, so every other
                # fee/payment view (admin list, parent dashboard, payment
                # history) needs no team-fee-aware logic of its own.
                players = list(team.players.all())
                Fee.objects.bulk_create(
                    Fee(
                        player=player,
                        description=form.cleaned_data["description"],
                        amount_due=form.cleaned_data["amount_due"],
                        due_date=form.cleaned_data["due_date"],
                        created_by=request.user,
                    )
                    for player in players
                )
                messages.success(
                    request,
                    f"Added a ${form.cleaned_data['amount_due']} "
                    f"\"{form.cleaned_data['description']}\" fee for "
                    f"{len(players)} player(s) on {team}.",
                )
                return redirect("accounts:admin_fees_list")

            fee = form.save(commit=False)
            fee.created_by = request.user
            fee.save()
            return redirect("accounts:admin_fee_detail", pk=fee.pk)
    else:
        form = FeeForm()
    return render(request, "accounts/admin_fee_form.html", {"form": form, "heading": "Add Fee"})


@login_required
def admin_fee_edit(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    fee = get_object_or_404(Fee, pk=pk)
    if request.method == "POST":
        form = FeeForm(request.POST, instance=fee)
        if form.is_valid():
            form.save()
            return redirect("accounts:admin_fee_detail", pk=fee.pk)
    else:
        form = FeeForm(instance=fee)
    return render(
        request, "accounts/admin_fee_form.html", {"form": form, "heading": "Edit Fee", "fee": fee}
    )


@login_required
def admin_fee_detail(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    fee = get_object_or_404(
        Fee.objects.select_related("player", "team", "reminder").prefetch_related("payments"), pk=pk
    )
    return render(
        request,
        "accounts/admin_fee_detail.html",
        {"fee": fee, "payment_form": PaymentForm()},
    )


@login_required
@require_POST
def admin_fee_record_payment(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    fee = get_object_or_404(Fee, pk=pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.fee = fee
        payment.recorded_by = request.user
        payment.save()
        payment_form = PaymentForm()
    else:
        payment_form = form

    # Re-fetch with a fresh prefetch -- the queryset above didn't prefetch
    # payments, and even if it had, the cache wouldn't include the row just
    # created, so fee.balance/amount_paid (which iterate fee.payments.all())
    # would read stale data.
    fee = Fee.objects.select_related("player", "team").prefetch_related("payments").get(pk=fee.pk)
    return render(
        request, "partials/_fee_ledger.html", {"fee": fee, "payment_form": payment_form}
    )


@login_required
def admin_coaches_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    coaches = (
        User.objects.filter(roles__role=Role.COACH)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related("team_assignments__team")
        .order_by("last_name", "first_name")
    )
    return render(request, "accounts/admin_coaches_list.html", {"coaches": coaches})


@login_required
def admin_schedule(request):
    """Entry point into every team's practice/tournament pages -- an admin
    isn't necessarily on any team's staff, so the coach dashboard's team
    switcher doesn't reach them. Includes not-yet-public teams."""
    if not request.user.is_admin:
        raise PermissionDenied
    teams = Team.objects.filter(is_deleted_placeholder=False).order_by("-season_year", "name")
    return render(request, "accounts/admin_schedule.html", {"teams": teams})


@login_required
def admin_coach_bio_edit(request, user_id):
    if not request.user.is_admin:
        raise PermissionDenied

    coach = get_object_or_404(User, pk=user_id, roles__role=Role.COACH)
    profile, _ = CoachProfile.objects.get_or_create(coach=coach)
    if request.method == "POST":
        form = CoachProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("accounts:admin_coaches_list")
    else:
        form = CoachProfileForm(instance=profile)
    return render(
        request, "accounts/admin_coach_bio_form.html", {"form": form, "coach": coach}
    )



@login_required
def coach_profile_edit(request):
    """A coach edits their own public coach page (bio, photo, contact
    email) -- same form admins use in admin_coach_bio_edit. Name and team
    assignments stay admin-managed."""
    if not request.user.is_coach:
        raise PermissionDenied

    profile, _ = CoachProfile.objects.get_or_create(coach=request.user)
    if request.method == "POST":
        form = CoachProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your coach profile has been updated.")
            return redirect("teams:coach_detail", pk=request.user.pk)
    else:
        form = CoachProfileForm(instance=profile)
    return render(
        request,
        "accounts/admin_coach_bio_form.html",
        {
            "form": form,
            "coach": request.user,
            "is_own_profile": True,
            "back_url": reverse("accounts:dashboard_coach"),
            "back_label": "Back to dashboard",
        },
    )

@login_required
def admin_tryout_posters_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    posters = TryoutPoster.objects.all()
    return render(request, "accounts/admin_tryout_posters_list.html", {"posters": posters})


@login_required
def admin_tryout_poster_add(request):
    if not request.user.is_admin:
        raise PermissionDenied

    if request.method == "POST":
        form = TryoutPosterForm(request.POST, request.FILES)
        if form.is_valid():
            poster = form.save(commit=False)
            poster.uploaded_by = request.user
            poster.save()
            return redirect("accounts:admin_tryout_posters_list")
    else:
        form = TryoutPosterForm()
    return render(
        request,
        "accounts/admin_tryout_poster_form.html",
        {"form": form, "heading": "Add Try-Out Poster"},
    )


@login_required
def admin_tryout_poster_edit(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    poster = get_object_or_404(TryoutPoster, pk=pk)
    if request.method == "POST":
        form = TryoutPosterForm(request.POST, request.FILES, instance=poster)
        if form.is_valid():
            form.save()
            return redirect("accounts:admin_tryout_posters_list")
    else:
        form = TryoutPosterForm(instance=poster)
    return render(
        request,
        "accounts/admin_tryout_poster_form.html",
        {"form": form, "heading": f"Edit: {poster.title}", "poster": poster},
    )


@login_required
@require_POST
def admin_tryout_poster_delete(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    poster = get_object_or_404(TryoutPoster, pk=pk)
    poster.delete()
    return redirect("accounts:admin_tryout_posters_list")


def _get_coach_team_or_404(user, team_id):
    return get_object_or_404(Team, pk=team_id, coach_assignments__coach=user)


def _get_roster_team_or_404(user, team_id):
    # Roster views (unlike the rest of the coach dashboard) are also open to
    # admins -- an admin isn't necessarily assigned to the team via
    # TeamCoach, so they get any team rather than _get_coach_team_or_404's
    # coach_assignments filter.
    if user.is_admin:
        return get_object_or_404(Team, pk=team_id)
    return _get_coach_team_or_404(user, team_id)


def _can_manage_tryout_signup(user, team):
    # The decision is editable from either dashboard
    # (coach_tryout_decision_change) -- an admin can act on any signup, a
    # coach only on their own team's, same scoping as roster/practice editing.
    return user.is_admin or TeamCoach.objects.filter(coach=user, team=team).exists()


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
def coach_roster_edit_player(request, team_id, player_id):
    if not (request.user.is_coach or request.user.is_admin):
        raise PermissionDenied
    team = _get_roster_team_or_404(request.user, team_id)
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


@login_required
def coach_tryouts(request):
    if not request.user.is_coach:
        raise PermissionDenied
    # A coach only ever sees sign-ups for the teams they coach, one team at
    # a time (the newest season first). An unknown or not-theirs ?team= just
    # falls back to the first team rather than erroring.
    teams = list(
        Team.objects.filter(is_deleted_placeholder=False, coach_assignments__coach=request.user)
        .distinct()
        .order_by("-season_year", "name")
    )
    selected_team = next((t for t in teams if str(t.pk) == request.GET.get("team")), None)
    if selected_team is None and teams:
        selected_team = teams[0]
    signups = TryoutSignup.objects.none()
    if selected_team:
        signups = (
            TryoutSignup.objects.filter(team=selected_team)
            .prefetch_related("positions")
            .order_by("player_last_name", "player_first_name")
        )
    return render(
        request,
        "accounts/coach_tryouts.html",
        {
            "signups": signups,
            "decision_choices": TryoutDecision.choices,
            "teams": teams,
            "selected_team": selected_team,
        },
    )


@login_required
@require_POST
def coach_tryout_decision_change(request, pk):
    signup = get_object_or_404(TryoutSignup.objects.select_related("team"), pk=pk)
    if not _can_manage_tryout_signup(request.user, signup.team):
        raise PermissionDenied

    new_decision = request.POST.get("coach_decision", "")
    if new_decision not in dict(TryoutDecision.choices):
        return HttpResponseBadRequest("Invalid decision")

    if new_decision != signup.coach_decision:
        TryoutDecisionChange.objects.create(
            signup=signup,
            old_decision=signup.coach_decision,
            new_decision=new_decision,
            changed_by=request.user,
        )
        signup.coach_decision = new_decision
        # A changed decision needs its own new email -- clear any earlier
        # send so the button/"Sent" badge (see _tryout_email_action.html)
        # reflects the current decision, not a stale one.
        signup.decision_emailed_at = None
        signup.save(update_fields=["coach_decision", "decision_emailed_at"])

    decision_html = render(
        request,
        "partials/_tryout_decision_select.html",
        {"signup": signup, "decision_choices": TryoutDecision.choices},
    ).content
    # The email action depends on coach_decision, which just changed --
    # sent out-of-band (hx-swap-oob) alongside the decision fragment above
    # so both cells update from this one request.
    email_html = render(
        request,
        "partials/_tryout_email_action.html",
        {"signup": signup, "oob": True},
    ).content
    return HttpResponse(decision_html + email_html)


@login_required
@require_POST
def coach_tryout_send_email(request, pk):
    """
    The simplified send flow: no admin "finalize" step (see CLAUDE.md) --
    a coach can send this one signup's acceptance/rejection email the
    moment its decision is set, independent of every other signup on the
    team. Creates the TryoutResponseInvite on demand (same token/expiry
    pattern the old admin-driven flow used) and marks
    TryoutSignup.decision_emailed_at so the button locks and shows "Sent".
    """
    if not request.user.is_coach:
        raise PermissionDenied

    signup = get_object_or_404(TryoutSignup.objects.select_related("team"), pk=pk)
    if not TeamCoach.objects.filter(coach=request.user, team=signup.team).exists():
        raise PermissionDenied

    if signup.coach_decision not in (TryoutDecision.INVITE, TryoutDecision.NOT_SELECTED):
        return HttpResponseBadRequest("Set a decision before sending an email")
    if signup.decision_emailed_at:
        # Already sent for the current decision -- no-op rather than
        # double-send (the button is disabled client-side too, but the
        # decision could've changed back via another tab/request).
        return render(request, "partials/_tryout_email_action.html", {"signup": signup})

    invite = (
        TryoutResponseInvite.objects.filter(signup=signup, responded_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if not invite or not invite.is_valid:
        invite = TryoutResponseInvite.objects.create(signup=signup, created_by=request.user)

    try:
        send_response_invite_email(invite, request)
    except Exception:
        logger.exception("Try-out decision email failed for signup %s", signup.pk)
        # Rendered inline rather than via the messages framework -- this
        # response only ever replaces the email-cell fragment (hx-swap
        # outerHTML), never a full page load, so a top-of-page message
        # would never actually be seen.
        return render(
            request, "partials/_tryout_email_action.html", {"signup": signup, "send_failed": True}
        )

    signup.decision_emailed_at = timezone.now()
    signup.save(update_fields=["decision_emailed_at"])
    return render(request, "partials/_tryout_email_action.html", {"signup": signup})



def _mass_email_teams(user):
    """Teams whose sign-ups `user` may email: any team for an admin, a
    coach's own teams otherwise (head or assistant -- same scoping as the
    rest of the coach pages). Never the "Deleted team" placeholder."""
    teams = Team.objects.filter(is_deleted_placeholder=False)
    if user.is_admin:
        return teams
    return teams.filter(coach_assignments__coach=user).distinct()


def _mass_email_recipients(signups):
    """One entry per parent email (case-insensitive), so a family with two
    kids trying out gets one copy that lists both."""
    families = {}
    for signup in signups:
        key = signup.parent_email.strip().lower()
        family = families.setdefault(
            key,
            {"email": signup.parent_email.strip(), "parent": signup.parent_full_name, "signups": []},
        )
        family["signups"].append(signup)
    return list(families.values())


@login_required
def tryout_mass_email(request):
    """
    "Email Families": a coach or admin emails every family that signed up
    for try-outs, optionally narrowed to one team and/or one decision. The
    recipient list is shown before sending and recomputed from the filter
    on POST (never taken from the browser). Each family gets its own copy
    (apps.tryouts.emails.send_tryout_mass_email), replies go to the sender,
    and every send is recorded as a TryoutMassEmail.
    """
    user = request.user
    if not (user.is_coach or user.is_admin):
        raise PermissionDenied

    allowed_teams = _mass_email_teams(user)
    params = request.POST if request.method == "POST" else request.GET
    team_id = params.get("team", "")
    decision = params.get("decision", "")
    selected_team = None
    if team_id:
        selected_team = get_object_or_404(allowed_teams, pk=team_id)
    if decision and decision not in dict(TryoutDecision.choices):
        return HttpResponseBadRequest("Invalid decision")

    signups = (
        TryoutSignup.objects.filter(team__in=[selected_team] if selected_team else allowed_teams)
        .select_related("team")
        .order_by("parent_last_name", "parent_first_name", "player_first_name")
    )
    if decision:
        signups = signups.filter(coach_decision=decision)
    all_recipients = _mass_email_recipients(signups)
    recipients = all_recipients
    for family in all_recipients:
        family["checked"] = True
    if request.method == "POST":
        # The coach may untick families. Only ever narrows the list computed
        # above from the filter, so a forged address can't be added.
        chosen = {e.strip().lower() for e in request.POST.getlist("recipient")}
        for family in all_recipients:
            family["checked"] = family["email"].lower() in chosen
        recipients = [r for r in all_recipients if r["checked"]]

    reply_to = user.email
    profile = getattr(user, "coach_profile", None)
    if profile and profile.contact_email:
        reply_to = profile.contact_email

    filter_query = f"?team={team_id}&decision={decision}"
    if request.method == "POST":
        form = TryoutMassEmailForm(request.POST)
        if not recipients:
            form.add_error(None, "No families are selected, so there's no one to email.")
        if form.is_valid():
            body = (
                f"{form.cleaned_data['body'].rstrip()}\n\n"
                f"--\nSent by {user.get_full_name() or user.email} through Choice Select. "
                "Reply to this email to reach them directly. If this landed in spam, please "
                'mark it "Not spam" so future emails reach your inbox.\n'
            )
            error = None
            try:
                sent = send_tryout_mass_email(
                    form.cleaned_data["subject"], body, [r["email"] for r in recipients], [reply_to]
                )
            except MassEmailError as exc:
                logger.exception("Try-out mass email failed after %s sends", len(exc.sent))
                sent, error = exc.sent, exc
            if sent:
                TryoutMassEmail.objects.create(
                    sent_by=user,
                    team=selected_team,
                    decision=decision,
                    subject=form.cleaned_data["subject"],
                    body=body,
                    recipients=sent,
                )
            if error is None:
                messages.success(request, f"Email sent to {len(sent)} famil{'y' if len(sent) == 1 else 'ies'}.")
                return redirect(reverse("accounts:tryout_mass_email") + filter_query)
            form.add_error(
                None,
                f"Sending failed after {len(sent)} of {len(recipients)} families. "
                "Nothing else was sent. Check the history below before trying again.",
            )
    else:
        form = TryoutMassEmailForm()

    # History: everything for an admin; for a coach, their own sends plus
    # anything sent to one of their teams.
    history = TryoutMassEmail.objects.select_related("sent_by", "team")
    if not user.is_admin:
        history = history.filter(Q(sent_by=user) | Q(team__in=allowed_teams))

    filter_teams = allowed_teams.filter(tryout_signups__isnull=False).distinct().order_by(
        "-season_year", "name"
    )
    return render(
        request,
        "accounts/tryout_mass_email.html",
        {
            "form": form,
            "recipients": recipients,
            "all_recipients": all_recipients,
            "filter_teams": filter_teams,
            "selected_team": selected_team,
            "selected_decision": decision,
            "decision_choices": TryoutDecision.choices,
            "reply_to": reply_to,
            "history": history[:25],
            "back_url": reverse(
                "accounts:admin_tryouts_list" if user.is_admin else "accounts:coach_tryouts"
            ),
        },
    )

@login_required
def dashboard_parent(request):
    if not request.user.is_parent:
        raise PermissionDenied

    links = (
        ParentPlayerLink.objects.filter(parent=request.user, removed_at__isnull=True)
        .select_related("player", "player__team")
        .prefetch_related(
            "player__fees__payments",
            Prefetch(
                "player__parent_links",
                queryset=ParentPlayerLink.objects.filter(removed_at__isnull=True).select_related(
                    "parent"
                ),
                to_attr="active_links",
            ),
        )
        .order_by("player__last_name", "player__first_name")
    )
    now = timezone.now()
    cards = []
    for link in links:
        player = link.player
        next_event = None
        if player.team:
            next_event = player.team.events.filter(start_datetime__gte=now).order_by("start_datetime").first()
        # Team-wide fees fan out into per-player Fee rows at creation time
        # (see admin_fee_add), so a plain player.fees.all() already picks
        # them up -- no separate team-fee handling needed here.
        balance = sum(fee.balance for fee in player.fees.all())
        primary_link = next((l for l in player.active_links if l.is_primary), None)
        cards.append(
            {
                "player": player,
                "next_event": next_event,
                "balance": balance,
                "primary_link": primary_link,
                "is_primary": link.is_primary,
                # Adults the current primary could hand "primary" to.
                "other_links": [l for l in player.active_links if l.pk != link.pk],
            }
        )

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


@login_required
def parent_player_profile_edit(request, player_id):
    """Profile editing now happens inline on the player page (teams.views.
    player_detail, which does the permission check); this URL only keeps old
    links and bookmarks working."""
    return redirect(reverse("teams:player_detail", args=[player_id]) + "#profile")


def _get_gallery_player_or_403(user, player_id):
    """Gallery editing is linked-parents-only -- no admin override here,
    unlike the profile form on player_detail (see PlayerGalleryPhoto)."""
    player = get_object_or_404(Player, pk=player_id)
    if not ParentPlayerLink.objects.filter(
        parent=user, player=player, removed_at__isnull=True
    ).exists():
        raise PermissionDenied
    return player


@login_required
@require_POST
def parent_player_gallery_add(request, player_id):
    player = _get_gallery_player_or_403(request.user, player_id)
    form = PlayerGalleryPhotoForm(request.POST, request.FILES, player=player)
    if form.is_valid():
        for image in form.cleaned_data["images"]:
            PlayerGalleryPhoto.objects.create(
                player=player, image=downsize_image(image), uploaded_by=request.user
            )
        count = len(form.cleaned_data["images"])
        messages.success(request, f"Added {count} photo{'s' if count != 1 else ''}.")
    else:
        for error in form.errors.get("images", []):
            messages.error(request, error)
    return redirect(reverse("teams:player_detail", args=[player.pk]) + "#gallery")


@login_required
@require_POST
def parent_player_gallery_delete(request, player_id, photo_id):
    player = _get_gallery_player_or_403(request.user, player_id)
    photo = get_object_or_404(PlayerGalleryPhoto, pk=photo_id, player=player)
    # Removes the stored file too (R2 or ./media) -- deleting the row alone
    # would leave it orphaned in storage.
    photo.image.delete(save=False)
    photo.delete()
    messages.success(request, "Photo deleted.")
    return redirect(reverse("teams:player_detail", args=[player.pk]) + "#gallery")


@login_required
def parent_invite_player(request, player_id):
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player

    invite = _open_invite_for(player, request.user)
    if request.method == "POST" and not invite:
        # At most MAX_LINKED_ADULTS_PER_PLAYER adults per kid, counting
        # open invites, so the page offers "Generate" only while a slot is left.
        if ParentInvite.slots_left(player) > 0:
            invite = ParentInvite.objects.create(player=player, created_by=request.user)
        else:
            messages.error(
                request,
                f"{player.first_name} already has the most adults allowed. Contact the club to add someone else.",
            )

    invite_url = None
    email_form = None
    if invite:
        invite_url = request.build_absolute_uri(reverse("accounts:invite_claim", args=[invite.token]))
        # The link itself is always shown (below); this is just the extra
        # "email it" option alongside it -- prefill with whoever it was
        # last sent to, so a resend doesn't need retyping the address.
        email_form = ParentInviteEmailForm(initial={"email": invite.invitee_email})

    linked_count = player.parent_links.filter(removed_at__isnull=True).count()
    return render(
        request,
        "accounts/parent_invite.html",
        {
            "player": player,
            "invite": invite,
            "invite_url": invite_url,
            "email_form": email_form,
            "linked_count": linked_count,
            "max_adults": MAX_LINKED_ADULTS_PER_PLAYER,
            "can_invite": ParentInvite.slots_left(player) > 0,
        },
    )


def _open_invite_for(player, user):
    """`user`'s current usable invite for `player`, if any -- a parent has
    at most one open invite per kid at a time."""
    return (
        ParentInvite.open_invites()
        .filter(player=player, created_by=user)
        .order_by("-created_at")
        .first()
    )


@login_required
@require_POST
def parent_invite_cancel(request, player_id):
    """Cancels the logged-in parent's open invite link for this kid. Only
    possible before anyone has used it -- a used link is already a
    parent-player link, which only an admin can remove."""
    if not request.user.is_parent:
        raise PermissionDenied
    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    invite = _open_invite_for(link.player, request.user)
    if invite:
        invite.cancelled_at = timezone.now()
        invite.save(update_fields=["cancelled_at"])
        messages.success(request, "Invite link cancelled. It can no longer be used.")
    else:
        messages.error(request, "There's no unused invite link to cancel.")
    return redirect("accounts:parent_invite_player", player_id=link.player_id)


@login_required
@require_POST
def parent_make_primary(request, player_id):
    """
    The kid's current primary parent hands "primary" to another adult
    linked to the same kid (ParentPlayerLink.save un-primaries their own
    link). Only the current primary can do this; admins use Django admin.
    """
    if not request.user.is_parent:
        raise PermissionDenied
    own_link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    if not own_link.is_primary:
        raise PermissionDenied
    new_link = get_object_or_404(
        ParentPlayerLink.objects.select_related("parent"),
        pk=request.POST.get("link_id"),
        player_id=player_id,
        removed_at__isnull=True,
    )
    if new_link.pk != own_link.pk:
        new_link.is_primary = True
        new_link.save(update_fields=["is_primary"])
        messages.success(
            request,
            f"{new_link.parent} is now {own_link.player.first_name}'s primary parent.",
        )
    return redirect("accounts:dashboard_parent")


@login_required
@require_POST
def parent_invite_send_email(request, player_id):
    """The optional "email it" action layered on top of parent_invite_player's copy/paste link -- doesn't replace it."""
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player

    invite = _open_invite_for(player, request.user)
    if not invite:
        raise PermissionDenied

    email_form = ParentInviteEmailForm(request.POST)
    if not email_form.is_valid():
        messages.error(request, "Enter a valid email address.")
        return redirect("accounts:parent_invite_player", player_id=player.pk)

    invite.invitee_email = email_form.cleaned_data["email"]
    invite.save(update_fields=["invitee_email"])

    try:
        send_parent_invite_email(invite, request)
    except Exception:
        logger.exception("Parent invite email failed for invite %s", invite.pk)
        # Parents see this, so point them at the copy/paste link rather
        # than at server configuration they can't do anything about.
        messages.error(
            request,
            "Couldn't send the email right now. You can still copy the link above and send it yourself.",
        )
    else:
        invite.emailed_at = timezone.now()
        invite.save(update_fields=["emailed_at"])
        messages.success(
            request,
            f"Emailed the invite link to {invite.invitee_email}. "
            "If they don't see it, ask them to check their spam folder.",
        )

    return redirect("accounts:parent_invite_player", player_id=player.pk)


def invite_claim(request, token):
    """
    Public -- no login required to view. Whoever holds this link can either
    confirm with their existing account (if already logged in) or create a
    new one on the spot; there's no pre-set invitee email on ParentInvite,
    so this is the only way to tie a specific person to the claim.
    """
    invite = get_object_or_404(
        ParentInvite.objects.select_related("player", "created_by"), token=token
    )

    if not invite.is_valid:
        return render(request, "accounts/invite_invalid.html", {"invite": invite})

    # Re-checked here, not just when the link was made: another adult may
    # have been linked since. Someone already linked to the kid isn't
    # adding anyone, so they're never blocked.
    already_linked = request.user.is_authenticated and invite.player.parent_links.filter(
        parent=request.user, removed_at__isnull=True
    ).exists()
    at_cap = (
        invite.player.parent_links.filter(removed_at__isnull=True).count()
        >= MAX_LINKED_ADULTS_PER_PLAYER
    )
    if at_cap and not already_linked:
        return render(request, "accounts/invite_invalid.html", {"invite": invite, "full": True})

    if request.user.is_authenticated:
        if request.method == "POST":
            _complete_invite_claim(invite, request.user)
            return redirect("accounts:dashboard")
        return render(request, "accounts/invite_claim_confirm.html", {"invite": invite})

    if request.method == "POST":
        form = InviteClaimSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            _complete_invite_claim(invite, user)
            auth_login(request, user)
            return redirect("accounts:dashboard")
    else:
        form = InviteClaimSignupForm()
    return render(request, "accounts/invite_claim_signup.html", {"invite": invite, "form": form})


def _complete_invite_claim(invite, user):
    # Only an *active* link counts: an adult whose earlier link was removed
    # gets a new one (removed links stay as history).
    ParentPlayerLink.objects.get_or_create(
        parent=user,
        player=invite.player,
        removed_at__isnull=True,
        defaults={"created_by": invite.created_by},
    )
    invite.claimed_at = timezone.now()
    invite.claimed_by = user
    invite.save(update_fields=["claimed_at", "claimed_by"])
    parent_role, _ = UserRole.objects.get_or_create(role=Role.PARENT)
    user.roles.add(parent_role)
