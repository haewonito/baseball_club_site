from django.shortcuts import render
from django.utils import timezone

from apps.teams.models import Team

from .models import Event


def schedule_list(request):
    """Public schedule, filterable by team. No login required."""
    team_id = request.GET.get("team", "")

    events = Event.objects.filter(start_datetime__gte=timezone.now()).select_related("team")
    if team_id:
        events = events.filter(team_id=team_id)

    return render(
        request,
        "schedule/list.html",
        {
            "events": events,
            "teams": Team.objects.order_by("-season_year", "division"),
            "selected_team_id": team_id,
        },
    )
