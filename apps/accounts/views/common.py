from django.shortcuts import get_object_or_404

from apps.teams.models import Team, TeamCoach


def _get_coach_team_or_404(user, team_id):
    return get_object_or_404(Team, pk=team_id, coach_assignments__coach=user)


def _get_roster_team_or_404(user, team_id):
    # Roster views (unlike the rest of the coach dashboard) are also open to
    # admins -- an admin isn't necessarily assigned to the team via
    # TeamCoach, so they get any team rather than _get_coach_team_or_404's
    # coach_assignments filter.
    if user.is_admin:
        return get_object_or_404(Team, pk=team_id)
    return _get_coach_team_or_404(user, team_id)


def _can_manage_tryout_signup(user, team):
    # The decision is editable from either dashboard
    # (coach_tryout_decision_change) -- an admin can act on any signup, a
    # coach only on their own team's, same scoping as roster/practice editing.
    return user.is_admin or TeamCoach.objects.filter(coach=user, team=team).exists()
