from django.db.models import Case, F, IntegerField, Prefetch, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.forms import GALLERY_MAX_PHOTOS, PlayerGalleryPhotoForm
from apps.accounts.models import ParentPlayerLink, Player, Role, User
from apps.fees.models import FEE_STATUS_LABELS

from .models import Team, TeamCoach, TeamCoachRole

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
    teams = Team.objects.filter(is_public=True, is_deleted_placeholder=False).order_by("-season_year", "division")
    return render(request, "teams/index.html", {"teams": teams})


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
    can_manage_schedule = user.is_authenticated and (
        user.is_admin or TeamCoach.objects.filter(coach=user, team=team).exists()
    )
    return render(
        request,
        "teams/detail.html",
        {
            "team": team,
            "upcoming_events": upcoming_events,
            "can_manage_schedule": can_manage_schedule,
        },
    )


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
    """Public coach bio detail. No login required. Same visibility rule as coach_index."""
    public_assignments = TeamCoach.objects.filter(team__is_public=True).select_related("team")
    coach = get_object_or_404(
        User.objects.filter(roles__role=Role.COACH)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related(Prefetch("team_assignments", queryset=public_assignments)),
        pk=pk,
    )
    return render(request, "teams/coach_detail.html", {"coach": coach})


def _player_viewer_info(request, player):
    """
    One player_detail page, three visibility tiers -- this decides which
    one a given request gets. 0 = no access (404), 1 = public tier only,
    2 = tier 1 + DOB/parent-contact (a coach of the player's team, or a
    parent linked to the player), 3 = tier 2 + fees/links/everything
    (admin). can_edit_profile is separate from tier: only admin or the
    specific linked parent may edit photo/description/is_public_profile
    (apps.accounts.views.parent_player_profile_edit) -- a coach can be
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
        "can_edit_gallery": can_edit_gallery,
        "gallery_photos": player.gallery_photos.all(),
    }
    if can_edit_gallery:
        context["gallery_form"] = PlayerGalleryPhotoForm(player=player)
        context["gallery_max_photos"] = GALLERY_MAX_PHOTOS
    if tier >= 2:
        context["parent_links"] = player.parent_links.filter(
            removed_at__isnull=True
        ).select_related("parent")
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
        context["tryout_signup"] = getattr(player, "tryout_signup", None)
    return render(request, "teams/player_detail.html", context)
