from django.contrib.auth import login as auth_login
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.forms import InviteClaimSignupForm
from apps.accounts.models import Role, UserRole
from apps.teams.models import Team

from .forms import TryoutSignupForm
from .models import TryoutDecision, TryoutFamilyResponse, TryoutResponseInvite


def signup(request):
    """Public try-out sign-up form. No login required."""
    accepting_tryouts = Team.objects.filter(accepting_tryouts=True).exists()
    form = None
    if accepting_tryouts:
        if request.method == "POST":
            form = TryoutSignupForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect("tryouts:signup_success")
        else:
            form = TryoutSignupForm()
    return render(
        request,
        "tryouts/signup.html",
        {"form": form, "accepting_tryouts": accepting_tryouts},
    )


def signup_success(request):
    return render(request, "tryouts/signup_success.html")


def respond(request, token):
    """
    Public -- no login required. A family whose signup has coach_decision
    INVITE either confirms with their existing account (if already logged
    in) or creates one on the spot, mirroring apps.accounts.ParentInvite's
    claim flow -- same UUID-token/single-response pattern via
    TryoutResponseInvite. A NOT_SELECTED signup's page is purely
    informational; there's no action to take, so no form/login handling
    applies there. UNDECIDED/MAYBE can't reach here -- see
    TryoutResponseInvite's docstring.
    """
    invite = get_object_or_404(
        TryoutResponseInvite.objects.select_related("signup", "signup__team"), token=token
    )

    if not invite.is_valid:
        return render(request, "tryouts/respond_invalid.html", {"invite": invite})

    signup = invite.signup
    can_respond = signup.coach_decision == TryoutDecision.INVITE

    form = None
    if can_respond:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "decline":
                _complete_response(signup, invite, TryoutFamilyResponse.DECLINED)
                return render(request, "tryouts/respond_done.html", {"signup": signup})
            if action == "accept":
                if request.user.is_authenticated:
                    _complete_response(signup, invite, TryoutFamilyResponse.ACCEPTED)
                    return render(request, "tryouts/respond_done.html", {"signup": signup})
                form = InviteClaimSignupForm(request.POST)
                if form.is_valid():
                    user = form.save()
                    _grant_parent_role(user)
                    auth_login(request, user)
                    _complete_response(signup, invite, TryoutFamilyResponse.ACCEPTED)
                    return render(request, "tryouts/respond_done.html", {"signup": signup})
        elif not request.user.is_authenticated:
            form = InviteClaimSignupForm(
                initial={
                    "first_name": signup.parent_first_name,
                    "last_name": signup.parent_last_name,
                    "email": signup.parent_email,
                }
            )

    return render(
        request,
        "tryouts/respond.html",
        {"signup": signup, "invite": invite, "can_respond": can_respond, "form": form},
    )


def _complete_response(signup, invite, response):
    signup.family_response = response
    signup.save(update_fields=["family_response"])
    invite.responded_at = timezone.now()
    invite.save(update_fields=["responded_at"])


def _grant_parent_role(user):
    parent_role, _ = UserRole.objects.get_or_create(role=Role.PARENT)
    user.roles.add(parent_role)
