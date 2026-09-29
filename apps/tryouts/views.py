import logging
from urllib.parse import urlencode

from django.contrib.auth import login as auth_login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import InviteClaimSignupForm
from apps.accounts.models import Role, User, UserRole
from apps.teams.models import Team

from .emails import send_signup_confirmation_email
from .forms import TryoutSignupForm
from .models import TryoutDecision, TryoutFamilyResponse, TryoutPoster, TryoutResponseInvite
from .roster import find_existing_player, promote_signup_to_roster

logger = logging.getLogger(__name__)


def signup(request):
    """
    Public try-out sign-up form. No login required. Open only while a
    try-out poster is active (the active poster is the current try-out --
    see TryoutPoster.is_active) and at least one team is accepting.

    If the parent's email already belongs to an account and they aren't
    logged in, the first submit isn't saved: the page pops up an offer to
    log in first (answers are kept in the session and refilled after
    login) or to submit anyway.
    """
    accepting_tryouts = (
        TryoutPoster.objects.filter(is_active=True).exists()
        and Team.objects.filter(accepting_tryouts=True, is_deleted_placeholder=False).exists()
    )
    form = None
    restored_draft = False
    if accepting_tryouts:
        if request.method == "POST":
            form = TryoutSignupForm(request.POST)
            if form.is_valid():
                email = form.cleaned_data["parent_email"]
                account_check = request.POST.get("account_check")
                if account_check == "login":
                    # Keep the answers across the login round trip; the GET
                    # below refills the form from them.
                    request.session[SIGNUP_DRAFT_SESSION_KEY] = {
                        key: values
                        for key, values in request.POST.lists()
                        if key not in ("csrfmiddlewaretoken", "account_check")
                    }
                    return redirect(
                        f"{reverse('accounts:login')}?"
                        + urlencode({"next": reverse("tryouts:signup"), "email": email})
                    )
                if (
                    account_check != "skip"
                    and not request.user.is_authenticated
                    and User.objects.filter(email__iexact=email).exists()
                ):
                    # Don't save yet: the template pops up "log in first?".
                    return render(
                        request,
                        "tryouts/signup.html",
                        {
                            "form": form,
                            "accepting_tryouts": accepting_tryouts,
                            "existing_account_email": email,
                        },
                    )
                signup = form.save()
                # The sign-up is already saved; a mail failure is only logged,
                # never shown to the family as a failed sign-up.
                try:
                    send_signup_confirmation_email(signup)
                except Exception:
                    logger.exception("Try-out sign-up confirmation email failed for signup %s", signup.pk)
                return redirect("tryouts:signup_success")
        else:
            draft = request.session.pop(SIGNUP_DRAFT_SESSION_KEY, None)
            if draft:
                form = TryoutSignupForm(initial=_draft_initial(draft))
                restored_draft = True
            elif request.user.is_authenticated:
                form = TryoutSignupForm(
                    initial={
                        "parent_first_name": request.user.first_name,
                        "parent_last_name": request.user.last_name,
                        "parent_email": request.user.email,
                    }
                )
            else:
                form = TryoutSignupForm()
    return render(
        request,
        "tryouts/signup.html",
        {
            "form": form,
            "accepting_tryouts": accepting_tryouts,
            "restored_draft": restored_draft,
        },
    )


# Session key for sign-up answers saved while the parent logs in (see signup).
SIGNUP_DRAFT_SESSION_KEY = "tryout_signup_draft"


def _draft_initial(draft):
    """Saved POST lists -> form initial: `positions` stays a list, the rest are single values."""
    return {
        key: values if key == "positions" else (values[0] if values else "")
        for key, values in draft.items()
    }


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
    applies there. UNDECIDED can't reach here -- see
    TryoutResponseInvite's docstring.
    """
    invite = get_object_or_404(
        TryoutResponseInvite.objects.select_related("signup", "signup__team"), token=token
    )

    # A signup whose team was deleted has no spot left to accept.
    if not invite.is_valid or invite.signup.team.is_deleted_placeholder:
        return render(request, "tryouts/respond_invalid.html", {"invite": invite})

    signup = invite.signup
    can_respond = signup.coach_decision == TryoutDecision.INVITE

    # A logged-in parent may already have this kid in the system (a
    # returning player). They confirm whether it's the same child; "yes"
    # moves that Player to this team rather than creating a duplicate.
    existing_player = None
    if can_respond and request.user.is_authenticated:
        existing_player = find_existing_player(signup, request.user)
    confirm_returning = False

    form = None
    if can_respond:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "decline":
                _complete_response(signup, invite, TryoutFamilyResponse.DECLINED)
                return render(request, "tryouts/respond_done.html", {"signup": signup})
            if action == "accept":
                if request.user.is_authenticated:
                    returning = request.POST.get("returning")
                    if existing_player and returning not in ("yes", "no"):
                        # No answer yet (e.g. JavaScript off): ask on the page.
                        confirm_returning = True
                    else:
                        _grant_parent_role(request.user)
                        _complete_response(
                            signup,
                            invite,
                            TryoutFamilyResponse.ACCEPTED,
                            responded_by=request.user,
                            existing_player=existing_player if returning == "yes" else None,
                        )
                        return render(request, "tryouts/respond_done.html", {"signup": signup})
                form = InviteClaimSignupForm(request.POST)
                if form.is_valid():
                    user = form.save()
                    _grant_parent_role(user)
                    auth_login(request, user)
                    _complete_response(
                        signup, invite, TryoutFamilyResponse.ACCEPTED, responded_by=user
                    )
                    return render(
                        request,
                        "tryouts/respond_done.html",
                        {"signup": signup, "account_created": True},
                    )
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
        {
            "signup": signup,
            "invite": invite,
            "can_respond": can_respond,
            "form": form,
            "existing_player": existing_player,
            "confirm_returning": confirm_returning,
        },
    )


def _complete_response(signup, invite, response, responded_by=None, existing_player=None):
    signup.family_response = response
    update_fields = ["family_response"]
    if responded_by is not None:
        signup.responded_by = responded_by
        update_fields.append("responded_by")
    signup.save(update_fields=update_fields)
    invite.responded_at = timezone.now()
    invite.save(update_fields=["responded_at"])
    if response == TryoutFamilyResponse.ACCEPTED:
        promote_signup_to_roster(
            signup, created_by=responded_by, existing_player=existing_player
        )


def _grant_parent_role(user):
    parent_role, _ = UserRole.objects.get_or_create(role=Role.PARENT)
    user.roles.add(parent_role)
