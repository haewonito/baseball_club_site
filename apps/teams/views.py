from django.db import transaction
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.db.models import Case, F, IntegerField, Prefetch, Value, When
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.forms import (
    CoachProfileForm,
    GALLERY_MAX_PHOTOS,
    TEAM_PHOTOS_MAX,
    TeamPhotoForm,
    downsize_image,
    PlayerGalleryPhotoForm,
    PlayerProfileForm,
    PlayerRosterForm,
)
from apps.accounts.models import ParentPlayerLink, Player, Role, User
from apps.fees.models import FEE_STATUS_LABELS

from .models import CoachProfile, Team, TeamCoach, TeamCoachRole, TeamPhoto

# Head coach listed before assistants -- explicit Case/When rather than
# relying on "head" sorting before "assistant" alphabetically, which would
# only work by coincidence of these particular choice values.
_HEAD_FIRST = Case(
    When(role=TeamCoachRole.HEAD, then=Value(0)),
    default=Value(1),
    output_field=IntegerField(),
)


def team_index(request):
    """Public teams index. No login required."""
    teams = (
        Team.objects.filter(is_public=True, is_deleted_placeholder=False)
        .prefetch_related(
            Prefetch("photos", queryset=TeamPhoto.objects.filter(is_featured=True), to_attr="featured_photos")
        )
        .order_by("-season_year", "division")
    )
    # One banner slide per team that has a featured photo; each links to the team.
    banner_teams = [team for team in teams if team.featured_photos]
    return render(request, "teams/index.html", {"teams": teams, "banner_teams": banner_teams})


def _can_manage_team(user, team):
    """This team's coaches, or any admin -- same rule as the schedule buttons."""
    return user.is_authenticated and (
        user.is_admin or TeamCoach.objects.filter(coach=user, team=team).exists()
    )


def team_detail(request, pk):
    """Public team detail: roster, coaching staff, filtered schedule."""
    coach_assignments = (
        TeamCoach.objects.select_related("coach")
        .annotate(_order=_HEAD_FIRST)
        .order_by("_order", "coach__last_name")
    )
    team = get_object_or_404(
        Team.objects.filter(is_public=True).prefetch_related(
            "players__positions",
            Prefetch("coach_assignments", queryset=coach_assignments),
        ),
        pk=pk,
    )
    upcoming_events = team.events.filter(start_datetime__gte=timezone.now())
    # Same rule as the coach/admin schedule pages this links into
    # (accounts.coach_events): this team's coaches, or any admin.
    user = request.user
    can_manage_schedule = _can_manage_team(user, team)
    context = {
        "team": team,
        "upcoming_events": upcoming_events,
        "can_manage_schedule": can_manage_schedule,
    }
    if can_manage_schedule:
        context["team_photos"] = team.photos.all()
        context["photo_form"] = TeamPhotoForm(team=team)
        context["team_photos_max"] = TEAM_PHOTOS_MAX
    return render(request, "teams/detail.html", context)


def _get_managed_team_or_403(user, team_id):
    team = get_object_or_404(Team, pk=team_id, is_deleted_placeholder=False)
    if not _can_manage_team(user, team):
        raise PermissionDenied
    return team


@login_required
@require_POST
def team_photo_add(request, team_id):
    team = _get_managed_team_or_403(request.user, team_id)
    form = TeamPhotoForm(request.POST, request.FILES, team=team)
    if form.is_valid():
        images = form.cleaned_data["images"]
        for image in images:
            TeamPhoto.objects.create(team=team, image=downsize_image(image), uploaded_by=request.user)
        messages.success(request, f"Added {len(images)} photo{'s' if len(images) != 1 else ''}.")
    else:
        for error in form.errors.get("images", []):
            messages.error(request, error)
    return redirect(reverse("teams:detail", args=[team.pk]) + "#photos")


@login_required
@require_POST
def team_photo_feature(request, team_id, photo_id):
    """Pick the picture shown on the Teams page, or clear the choice."""
    team = _get_managed_team_or_403(request.user, team_id)
    photo = get_object_or_404(TeamPhoto, pk=photo_id, team=team)
    with transaction.atomic():
        if photo.is_featured:
            photo.is_featured = False
            photo.save(update_fields=["is_featured"])
            messages.success(request, "That photo is no longer shown on the Teams page.")
        else:
            photo.is_featured = True  # save() un-features the previous one
            photo.save(update_fields=["is_featured"])
            messages.success(request, "That photo is now shown on the Teams page.")
    return redirect(reverse("teams:detail", args=[team.pk]) + "#photos")


@login_required
@require_POST
def team_photo_delete(request, team_id, photo_id):
    team = _get_managed_team_or_403(request.user, team_id)
    photo = get_object_or_404(TeamPhoto, pk=photo_id, team=team)
    photo.image.delete(save=False)  # also remove the stored file
    photo.delete()
    messages.success(request, "Photo deleted.")
    return redirect(reverse("teams:detail", args=[team.pk]) + "#photos")


def coach_index(request):
    """
    Public coach bios. No login required. Every coach is listed regardless
    of team visibility -- a coach whose only assignment is on a not-yet-
    public team (see Team.is_public) still shows up, just with no team
    listed ("TBA" in the template) rather than leaking the hidden team.
    """
    public_assignments = TeamCoach.objects.filter(team__is_public=True).select_related("team")
    coaches = (
        User.objects.filter(roles__role=Role.COACH)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related(Prefetch("team_assignments", queryset=public_assignments))
        # Pinned coaches (CoachProfile.list_first -- the club owner) first,
        # then by last name. A coach with no profile yet sorts as unpinned.
        .order_by(F("coach_profile__list_first").desc(nulls_last=True), "last_name", "first_name")
    )
    return render(request, "teams/coaches.html", {"coaches": coaches})


def coach_detail(request, pk):
    """
    Public coach bio detail. No login required. Same visibility rule as
    coach_index. The coach themself, or an admin, also gets an inline
    "Edit Profile" form (bio, photo, contact email) that posts back here;
    name and team assignments stay admin-managed in Django admin.
    """
    public_assignments = TeamCoach.objects.filter(team__is_public=True).select_related("team")
    coach = get_object_or_404(
        User.objects.filter(roles__role=Role.COACH)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related(Prefetch("team_assignments", queryset=public_assignments)),
        pk=pk,
    )
    can_edit = request.user.is_authenticated and (
        request.user.pk == coach.pk or request.user.is_admin
    )
    form = None
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        profile, _ = CoachProfile.objects.get_or_create(coach=coach)
        form = CoachProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Coach profile updated.")
            return redirect("teams:coach_detail", pk=coach.pk)
    elif can_edit:
        profile, _ = CoachProfile.objects.get_or_create(coach=coach)
        form = CoachProfileForm(instance=profile)
    return render(request, "teams/coach_detail.html", {"coach": coach, "form": form})


def _player_viewer_info(request, player):
    """
    One player_detail page, three visibility tiers -- this decides which
    one a given request gets. 0 = no access (404), 1 = public tier only,
    2 = tier 1 + DOB/parent-contact (a coach of the player's team, or a
    parent linked to the player), 3 = tier 2 + fees/links/everything
    (admin). can_edit_profile is separate from tier: only admin or the
    specific linked parent may edit photo/description/is_public_profile
    (the inline form on player_detail itself) -- a coach can be
    tier 2 without ever getting edit rights.
    """
    user = request.user
    if user.is_authenticated:
        if user.is_admin:
            return 3, True
        if ParentPlayerLink.objects.filter(
            parent=user, player=player, removed_at__isnull=True
        ).exists():
            return 2, True
        if player.team and TeamCoach.objects.filter(coach=user, team=player.team).exists():
            return 2, False
    if player.is_public_profile and player.team and player.team.is_public:
        return 1, False
    return 0, False


def player_detail(request, pk):
    """
    Public URL, but not necessarily public content -- see
    _player_viewer_info. A private player 404s for anyone who isn't
    their coach/parent/an admin, rather than confirming the player
    exists at all.
    """
    player = get_object_or_404(
        Player.objects.select_related("team").prefetch_related("positions"), pk=pk
    )
    tier, can_edit_profile = _player_viewer_info(request, player)
    if tier == 0:
        raise Http404

    # Two inline forms post back to this page: "Edit Profile" (photo,
    # description, public toggle; linked parent or admin) and "Edit Roster
    # Info" (name, DOB, jersey, positions; that team's coach or an admin).
    # A hidden form_kind field says which one was submitted, and each is
    # refused unless the viewer could see its button.
    can_edit_roster = tier >= 3 or (
        tier == 2
        and player.team_id is not None
        and TeamCoach.objects.filter(coach=request.user, team=player.team).exists()
    )
    profile_form = None
    roster_form = None
    if request.method == "POST":
        if request.POST.get("form_kind") == "roster":
            if not can_edit_roster:
                raise PermissionDenied
            roster_form = PlayerRosterForm(request.POST, instance=player, prefix="roster")
            if roster_form.is_valid():
                roster_form.save()
                return redirect("teams:player_detail", pk=player.pk)
        else:
            if not can_edit_profile:
                raise PermissionDenied
            profile_form = PlayerProfileForm(request.POST, request.FILES, instance=player)
            if profile_form.is_valid():
                profile_form.save()
                return redirect("teams:player_detail", pk=player.pk)
        # Validation assigns the rejected values onto `player`; show the
        # saved ones in the page and keep the rejected ones in the form.
        player = Player.objects.select_related("team").prefetch_related("positions").get(pk=pk)
    if can_edit_profile and profile_form is None:
        profile_form = PlayerProfileForm(instance=player)
    if can_edit_roster and roster_form is None:
        roster_form = PlayerRosterForm(instance=player, prefix="roster")

    # Gallery editing is linked-parents-only (no admin override, unlike
    # can_edit_profile) -- see PlayerGalleryPhoto.
    can_edit_gallery = (
        request.user.is_authenticated
        and ParentPlayerLink.objects.filter(
            parent=request.user, player=player, removed_at__isnull=True
        ).exists()
    )
    context = {
        "player": player,
        "tier": tier,
        "can_edit_profile": can_edit_profile,
        "profile_form": profile_form,
        "roster_form": roster_form,
        "can_edit_gallery": can_edit_gallery,
        "gallery_photos": player.gallery_photos.all(),
    }
    if can_edit_gallery:
        context["gallery_form"] = PlayerGalleryPhotoForm(player=player)
        context["gallery_max_photos"] = GALLERY_MAX_PHOTOS
    if tier >= 2:
        # Primary parent first, then the usual last-name order (Meta.ordering).
        context["parent_links"] = (
            player.parent_links.filter(removed_at__isnull=True)
            .select_related("parent")
            .order_by("-is_primary", "parent__last_name", "parent__first_name")
        )
    if tier >= 3:
        context["fee_rows"] = [
            {"fee": fee, "balance": fee.balance, "status_label": FEE_STATUS_LABELS.get(fee.status, fee.status)}
            for fee in player.fees.prefetch_related("payments")
        ]
        # Full history (including removed links), not just the active
        # ones tier 2 gets above -- matches CLAUDE.md's admin capability
        # "parent-player link management/history".
        context["link_history"] = player.parent_links.select_related(
            "parent", "created_by", "removed_by"
        ).order_by("-created_at")
        # One per season for a returning player (see TryoutSignup.promoted_player).
        context["tryout_signups"] = player.tryout_signups.select_related("team").order_by(
            "submitted_at"
        )
    return render(request, "teams/player_detail.html", context)
