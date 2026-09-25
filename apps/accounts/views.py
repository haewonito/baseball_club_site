from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.fees.models import Fee, Payment
from apps.schedule.models import Event, EventType
from apps.teams.models import CoachProfile, PlayerPosition, Team, TeamCoach
from apps.tryouts.emails import send_response_invite_email
from apps.tryouts.models import (
    TryoutDecision,
    TryoutDecisionChange,
    TryoutFamilyResponse,
    TryoutResponseInvite,
    TryoutSignup,
    TryoutStatus,
    TryoutStatusChange,
)

from .forms import (
    CoachProfileForm,
    FeeForm,
    InviteClaimSignupForm,
    PaymentForm,
    PlayerRosterForm,
    PracticeEventForm,
)
from .models import ParentInvite, ParentPlayerLink, Player, Role, User, UserRole

FEE_STATUS_LABELS = {
    "paid": "Paid",
    "partially_paid": "Partially Paid",
    "overdue": "Overdue",
    "unpaid": "Unpaid",
}


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

    signups = (
        TryoutSignup.objects.select_related("team", "promoted_player")
        .prefetch_related("positions")
        .order_by("-submitted_at")
    )
    years = [
        (year, f"{year - 1}-{year}")
        for year in TryoutSignup.objects.order_by("-team__season_year")
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
            "status_choices": TryoutStatus.choices,
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
    status_changes = signup.status_changes.select_related("changed_by").order_by("-changed_at")
    decision_changes = signup.decision_changes.select_related("changed_by").order_by("-changed_at")

    return render(
        request,
        "accounts/admin_tryout_detail.html",
        {
            "signup": signup,
            "status_choices": TryoutStatus.choices,
            "status_changes": status_changes,
            "decision_changes": decision_changes,
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


@login_required
@require_POST
def admin_tryout_promote(request, pk):
    """
    Turn an accepted sign-up into a real roster Player -- CLAUDE.md's
    roster-promotion plan, step 8. No re-entry: Player fields and
    positions come straight from the sign-up/TryoutSignupPosition rows.
    The parent link uses signup.responded_by (the account created/
    confirmed during the accept flow) rather than matching on
    parent_email, since the family could've entered a different email
    there. Fees intentionally aren't touched -- see CLAUDE.md.
    """
    if not request.user.is_admin:
        raise PermissionDenied

    signup = get_object_or_404(
        TryoutSignup.objects.select_related("team").prefetch_related("positions"), pk=pk
    )
    if signup.family_response != TryoutFamilyResponse.ACCEPTED:
        raise PermissionDenied
    if signup.promoted_player_id:
        return redirect("accounts:admin_tryout_detail", pk=signup.pk)
    if not signup.date_of_birth:
        messages.error(request, "Can't promote -- this sign-up is missing a date of birth.")
        return redirect("accounts:admin_tryout_detail", pk=signup.pk)

    player = Player.objects.create(
        first_name=signup.player_first_name,
        last_name=signup.player_last_name,
        date_of_birth=signup.date_of_birth,
        team=signup.team,
    )
    PlayerPosition.objects.bulk_create(
        PlayerPosition(player=player, position=p.position) for p in signup.positions.all()
    )
    signup.promoted_player = player
    signup.save(update_fields=["promoted_player"])

    if signup.responded_by_id:
        ParentPlayerLink.objects.get_or_create(
            parent=signup.responded_by, player=player, defaults={"created_by": request.user}
        )
    else:
        messages.warning(
            request,
            f"{player} was added, but no parent account was recorded for this sign-up -- "
            "link one manually via the Django admin's Parent Player Links.",
        )

    messages.success(request, f'{player} added to {signup.team.name}\'s roster.')
    return redirect("accounts:admin_tryout_detail", pk=signup.pk)


@login_required
def admin_fees_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    only_outstanding = request.GET.get("outstanding") == "1"
    fees = Fee.objects.select_related("player", "team").prefetch_related("payments").order_by("-created_at")

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
        Fee.objects.select_related("player", "team").prefetch_related("payments"), pk=pk
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
    other_teams = Team.objects.exclude(pk=team.pk).order_by("-season_year", "name")
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
    signups = TryoutSignup.objects.select_related("team").prefetch_related("positions").order_by(
        "-submitted_at"
    )
    # "All teams, all years" stays the coach dashboard's baseline view --
    # the team filter below narrows what's *shown*, it's not a permission
    # boundary (that's still my_team_ids, for the decision/email actions).
    teams = Team.objects.filter(
        pk__in=signups.values_list("team_id", flat=True)
    ).distinct().order_by("-season_year", "name")
    selected_team_id = request.GET.get("team")
    if selected_team_id:
        signups = signups.filter(team_id=selected_team_id)

    # Decision-making (and now, sending its email) is scoped to the coach's
    # own team(s) -- viewing every signup stays "all teams, all years" per
    # the coach dashboard's design, but the decision dropdown and send
    # button only render as editable for the rows this coach is actually
    # allowed to act on.
    my_team_ids = set(
        TeamCoach.objects.filter(coach=request.user).values_list("team_id", flat=True)
    )
    return render(
        request,
        "accounts/coach_tryouts.html",
        {
            "signups": signups,
            "decision_choices": TryoutDecision.choices,
            "my_team_ids": my_team_ids,
            "teams": teams,
            "selected_team_id": selected_team_id,
        },
    )


@login_required
@require_POST
def coach_tryout_decision_change(request, pk):
    if not request.user.is_coach:
        raise PermissionDenied

    signup = get_object_or_404(TryoutSignup.objects.select_related("team"), pk=pk)
    if not TeamCoach.objects.filter(coach=request.user, team=signup.team).exists():
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

    invite = (
        ParentInvite.objects.filter(player=player, created_by=request.user, claimed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if invite and not invite.is_valid:
        invite = None

    if request.method == "POST" and not invite:
        invite = ParentInvite.objects.create(player=player, created_by=request.user)

    invite_url = None
    if invite:
        invite_url = request.build_absolute_uri(reverse("accounts:invite_claim", args=[invite.token]))

    return render(
        request,
        "accounts/parent_invite.html",
        {"player": player, "invite": invite, "invite_url": invite_url},
    )


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
    ParentPlayerLink.objects.get_or_create(
        parent=user, player=invite.player, defaults={"created_by": invite.created_by}
    )
    invite.claimed_at = timezone.now()
    invite.claimed_by = user
    invite.save(update_fields=["claimed_at", "claimed_by"])
    parent_role, _ = UserRole.objects.get_or_create(role=Role.PARENT)
    user.roles.add(parent_role)
