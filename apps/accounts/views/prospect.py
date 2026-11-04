
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.tryouts.forms import ProspectivePlayerForm, TryoutSignupEditForm
from apps.tryouts.models import TryoutDecision, TryoutDecisionChange, TryoutSignup


@login_required
def dashboard_prospect(request):
    """A family's saved kids and try-out sign-ups. Open to any logged-in user: it's only their own data."""
    user = request.user
    kids = user.prospective_players.filter(promoted_player__isnull=True).prefetch_related("positions")
    signups = (
        TryoutSignup.objects.filter(Q(user=user) | Q(parent_email__iexact=user.email))
        .select_related("team")
        .order_by("-submitted_at")
    )
    return render(
        request, "accounts/dashboard_prospect.html", {"kids": kids, "signups": signups}
    )


def _get_prospect_or_404(user, pk):
    return get_object_or_404(user.prospective_players, pk=pk, promoted_player__isnull=True)


@login_required
def prospect_player_add(request):
    form = ProspectivePlayerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.user = request.user
        kid = form.save()
        messages.success(request, f"Saved {kid.first_name}.")
        return redirect("accounts:dashboard_prospect")
    return render(request, "accounts/prospect_player_form.html", {"form": form, "kid": None})


@login_required
def prospect_player_edit(request, pk):
    kid = _get_prospect_or_404(request.user, pk)
    form = ProspectivePlayerForm(request.POST or None, instance=kid)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {kid.first_name}.")
        return redirect("accounts:dashboard_prospect")
    return render(request, "accounts/prospect_player_form.html", {"form": form, "kid": kid})


@login_required
@require_POST
def prospect_player_delete(request, pk):
    kid = _get_prospect_or_404(request.user, pk)
    kid.delete()
    messages.success(request, f"Removed {kid.first_name}.")
    return redirect("accounts:dashboard_prospect")


def _get_family_signup(request, pk):
    """The family's own sign-up (by account or parent email), or None after explaining why it's locked."""
    user = request.user
    signup = get_object_or_404(
        TryoutSignup.objects.select_related("team"),
        Q(user=user) | Q(parent_email__iexact=user.email),
        pk=pk,
    )
    if not signup.family_can_change:
        messages.error(
            request,
            f"{signup.player_full_name}'s sign-up can no longer be changed here. Please contact the club.",
        )
        return None
    return signup


@login_required
def prospect_signup_edit(request, pk):
    """A family edits a try-out sign-up until a decision email has been sent."""
    signup = _get_family_signup(request, pk)
    if signup is None:
        return redirect("accounts:dashboard_prospect")

    old_team = signup.team
    form = TryoutSignupEditForm(request.POST or None, instance=signup, user=request.user)
    if request.method == "POST" and form.is_valid():
        signup = form.save()
        signup.family_edited_at = timezone.now()
        update_fields = ["family_edited_at"]
        if signup.team_id != old_team.pk and signup.coach_decision != TryoutDecision.UNDECIDED:
            # The new team's coaches haven't seen this kid: their call starts over.
            TryoutDecisionChange.objects.create(
                signup=signup,
                old_decision=signup.coach_decision,
                new_decision=TryoutDecision.UNDECIDED,
                changed_by=request.user,
            )
            signup.coach_decision = TryoutDecision.UNDECIDED
            update_fields.append("coach_decision")
        signup.save(update_fields=update_fields)
        messages.success(request, f"Saved {signup.player_full_name}'s sign-up.")
        return redirect("accounts:dashboard_prospect")
    return render(request, "accounts/prospect_signup_form.html", {"form": form, "signup": signup})


@login_required
@require_POST
def prospect_signup_withdraw(request, pk):
    """Withdraws a sign-up. Before the try-out the row is deleted; after it, it stays on the
    coaches' list crossed out (withdrawn_at)."""
    signup = _get_family_signup(request, pk)
    if signup is None:
        return redirect("accounts:dashboard_prospect")

    name = signup.player_full_name
    if signup.tryout_has_happened:
        signup.withdrawn_at = timezone.now()
        signup.save(update_fields=["withdrawn_at"])
    else:
        signup.delete()
    messages.success(request, f"{name} was withdrawn from the try-out.")
    return redirect("accounts:dashboard_prospect")
