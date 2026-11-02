import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.teams.models import Team
from apps.tryouts.emails import (
    MassEmailError,
    send_personalized_mass_email,
    send_tryout_mass_email,
)
from apps.tryouts.models import TryoutDecision, TryoutMassEmail, TryoutSignup

from ..emails import make_unsubscribe_token
from ..forms import TryoutMassEmailForm
from ..models import ParentPlayerLink, User

logger = logging.getLogger(__name__)


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
            {"email": signup.parent_email.strip(), "parent": signup.parent_full_name, "items": []},
        )
        family["items"].append(
            {
                "player": signup.player_full_name,
                "team": signup.team.display_name,
                "detail": signup.get_coach_decision_display(),
            }
        )
    return list(families.values())


def _mass_email_roster_recipients(teams):
    """Same shape, for the adults actively linked to players currently on
    `teams`. One entry per parent email, listing each of their kids."""
    links = (
        ParentPlayerLink.objects.filter(removed_at__isnull=True, player__team__in=teams)
        .select_related("parent", "player", "player__team")
        .order_by("parent__last_name", "parent__first_name", "player__first_name")
    )
    families = {}
    for link in links:
        key = link.parent.email.strip().lower()
        family = families.setdefault(
            key,
            {"email": link.parent.email.strip(), "parent": str(link.parent), "items": []},
        )
        family["items"].append(
            {"player": str(link.player), "team": link.player.team.display_name, "detail": ""}
        )
    return list(families.values())


def _interested_users():
    """Accounts that ticked the info-emails opt-in, confirmed their address and haven't left."""
    return User.objects.filter(
        info_emails_opt_in=True, email_verified=True, is_active=True
    ).prefetch_related("prospective_players")


def _mass_email_interested_recipients():
    """Same shape as the other audiences, one entry per opted-in account; `user` is kept for the unsubscribe link."""
    families = []
    for user in _interested_users():
        kids = [k.first_name for k in user.prospective_players.all() if k.promoted_player_id is None]
        families.append(
            {
                "email": user.email.strip(),
                "parent": str(user),
                "user": user,
                "items": [{"player": ", ".join(kids) or "\u2014", "team": "Not on a team", "detail": ""}],
            }
        )
    return families


# Appended to every "interested families" email, below the sender line.
INTERESTED_FOOTER = (
    "You're getting this because you registered on the Choice Select site and chose to "
    "receive club emails.\nUnsubscribe any time: {url}\n"
)


@login_required
def tryout_mass_email(request):
    """
    "Email Families": a coach or admin emails either the families that signed
    up for try-outs (audience=tryouts, optionally narrowed by decision) or the
    families of players currently on a roster (audience=roster), for one team
    or all of their teams (an admin's "all teams" is everyone). The
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
    audience = params.get("audience", "roster")
    if audience not in ("roster", "tryouts", "interested"):
        return HttpResponseBadRequest("Invalid audience")
    if audience == "interested":
        # Not tied to any team, and it's the club's list of registered
        # families, so it's an admin-only send.
        if not user.is_admin:
            raise PermissionDenied
        team_id = ""
    if audience != "tryouts":
        decision = ""
    selected_team = None
    if team_id:
        selected_team = get_object_or_404(allowed_teams, pk=team_id)
    if decision and decision not in dict(TryoutDecision.choices):
        return HttpResponseBadRequest("Invalid decision")

    scope = [selected_team] if selected_team else allowed_teams
    if audience == "roster":
        all_recipients = _mass_email_roster_recipients(scope)
    elif audience == "interested":
        all_recipients = _mass_email_interested_recipients()
    else:
        signups = (
            TryoutSignup.objects.filter(team__in=scope)
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

    filter_query = f"?audience={audience}&team={team_id}&decision={decision}"
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
                if audience == "interested":
                    # Each person gets their own unsubscribe link, in the
                    # body and as a List-Unsubscribe header (mail apps show
                    # it as an Unsubscribe button).
                    messages_out = []
                    for r in recipients:
                        url = request.build_absolute_uri(
                            reverse("accounts:unsubscribe", args=[make_unsubscribe_token(r["user"])])
                        )
                        messages_out.append(
                            (
                                r["email"],
                                f"{body}\n{INTERESTED_FOOTER.format(url=url)}",
                                {
                                    "List-Unsubscribe": f"<{url}>",
                                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                                },
                            )
                        )
                    sent = send_personalized_mass_email(
                        form.cleaned_data["subject"], messages_out, [reply_to]
                    )
                else:
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
                    audience=audience,
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

    if audience == "interested":
        filter_teams = allowed_teams.none()
    elif audience == "roster":
        filter_teams = allowed_teams.filter(players__isnull=False)
    else:
        filter_teams = allowed_teams.filter(tryout_signups__isnull=False)
    filter_teams = filter_teams.distinct().order_by("-season_year", "name")
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
            "audience": audience,
            "decision_choices": TryoutDecision.choices,
            "reply_to": reply_to,
            "history": history[:25],
            "back_url": reverse(
                ("accounts:dashboard_admin" if user.is_admin else "accounts:dashboard_coach")
                if audience != "tryouts"
                else ("accounts:admin_tryouts_list" if user.is_admin else "accounts:coach_tryouts")
            ),
            "back_label": "Back to dashboard" if audience != "tryouts" else "Back to try-out sign-ups",
        },
    )
