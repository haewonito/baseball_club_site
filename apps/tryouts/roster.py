from django.db import transaction

from apps.accounts.models import ParentPlayerLink, Player
from apps.teams.models import PlayerPosition


@transaction.atomic
def promote_signup_to_roster(signup, created_by):
    """
    Turn an accepted sign-up into a real roster Player -- CLAUDE.md's
    roster-promotion plan, step 8. No re-entry: Player fields and
    positions come straight from the sign-up/TryoutSignupPosition rows.
    The parent link uses signup.responded_by (the account created/
    confirmed during the accept flow) rather than matching on
    parent_email, since the family could've entered a different email
    there. Fees intentionally aren't touched -- see CLAUDE.md.

    Runs automatically when a family accepts (apps.tryouts.views.respond),
    with the admin's "Promote to Roster" button as the fallback. Returns
    the Player, or None if it can't promote: already promoted, no date of
    birth (optional on the sign-up form but required on Player), or its
    team was deleted (the signup is on the "Deleted team" placeholder).
    """
    if signup.promoted_player_id or not signup.date_of_birth or signup.team.is_deleted_placeholder:
        return None

    player = Player.objects.create(
        first_name=signup.player_first_name,
        last_name=signup.player_last_name,
        date_of_birth=signup.date_of_birth,
        team=signup.team,
    )
    PlayerPosition.objects.bulk_create(
        PlayerPosition(player=player, position=p.position) for p in signup.positions.all()
    )
    signup.promoted_player = player
    signup.save(update_fields=["promoted_player"])

    if signup.responded_by_id:
        ParentPlayerLink.objects.get_or_create(
            parent=signup.responded_by, player=player, defaults={"created_by": created_by}
        )
    return player
