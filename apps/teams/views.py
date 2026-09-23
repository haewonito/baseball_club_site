from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Team


def team_index(request):
    """Public teams index. No login required."""
    teams = Team.objects.order_by("-season_year", "division")
    return render(request, "teams/index.html", {"teams": teams})


def team_detail(request, pk):
    """Public team detail: roster, coaching staff, filtered schedule."""
    team = get_object_or_404(
        Team.objects.prefetch_related("players__positions", "coach_assignments__coach"),
        pk=pk,
    )
    upcoming_events = team.events.filter(start_datetime__gte=timezone.now())
    return render(
        request,
        "teams/detail.html",
        {"team": team, "upcoming_events": upcoming_events},
    )
