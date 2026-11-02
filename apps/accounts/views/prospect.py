
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.tryouts.forms import ProspectivePlayerForm
from apps.tryouts.models import TryoutSignup



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
