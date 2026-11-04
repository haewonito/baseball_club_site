import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.teams.models import Team, TeamCoach
from apps.tryouts.emails import send_response_invite_email
from apps.tryouts.models import (
    TryoutDecision,
    TryoutDecisionChange,
    TryoutResponseInvite,
    TryoutSignup,
)


logger = logging.getLogger(__name__)
from .common import _can_manage_tryout_signup


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
            # Withdrawn sign-ups (crossed out on the page) go at the end.
            .order_by(F("withdrawn_at").asc(nulls_first=True), "player_last_name", "player_first_name")
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

    if signup.is_withdrawn:
        return HttpResponseBadRequest("This sign-up was withdrawn")

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

    if signup.is_withdrawn:
        return HttpResponseBadRequest("This sign-up was withdrawn")
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
