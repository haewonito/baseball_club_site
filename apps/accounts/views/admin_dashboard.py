
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.teams.models import Team
from apps.tryouts.roster import find_existing_player, promote_signup_to_roster
from apps.tryouts.models import TryoutDecision, TryoutFamilyResponse, TryoutPoster, TryoutSignup

from ..forms import TryoutPosterForm
from ..models import Role, User


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
        messages.success(
            request,
            f"{player} (returning player) moved to {signup.team.display_name}'s roster.",
        )
    else:
        messages.success(request, f'{player} added to {signup.team.display_name}\'s roster.')
    return redirect("accounts:admin_tryout_detail", pk=signup.pk)


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
