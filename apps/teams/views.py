from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.models import Role, User

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
    teams = Team.objects.filter(is_public=True).order_by("-season_year", "division")
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
    return render(
        request,
        "teams/detail.html",
        {"team": team, "upcoming_events": upcoming_events},
    )


def coach_index(request):
    """
    Public coach bios. No login required. A coach whose every assignment is
    on a not-yet-public team (see Team.is_public) doesn't appear at all --
    their whole public presence would otherwise be tied to a hidden team.
    """
    public_assignments = TeamCoach.objects.filter(team__is_public=True).select_related("team")
    coaches = (
        User.objects.filter(roles__role=Role.COACH, team_assignments__team__is_public=True)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related(Prefetch("team_assignments", queryset=public_assignments))
        .order_by("last_name", "first_name")
    )
    return render(request, "teams/coaches.html", {"coaches": coaches})


def coach_detail(request, pk):
    """Public coach bio detail. No login required. Same is_public rule as coach_index."""
    public_assignments = TeamCoach.objects.filter(team__is_public=True).select_related("team")
    coach = get_object_or_404(
        User.objects.filter(roles__role=Role.COACH, team_assignments__team__is_public=True)
        .distinct()
        .select_related("coach_profile")
        .prefetch_related(Prefetch("team_assignments", queryset=public_assignments)),
        pk=pk,
    )
    return render(request, "teams/coach_detail.html", {"coach": coach})
