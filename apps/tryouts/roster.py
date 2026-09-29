from django.db import transaction

from apps.accounts.models import ParentPlayerLink, Player
from apps.teams.models import PlayerPosition


def find_existing_player(signup, parent):
    """
    A player already in the system who looks like this sign-up's kid: same
    first/last name (ignoring case), actively linked to `parent` (the
    account accepting the spot), and the same date of birth when both have
    one. Used to ask the family (or admin) whether this is a returning
    player, so accepting moves that Player instead of creating a duplicate.
    Returns None when there's no parent account or no match.
    """
    if parent is None:
        return None
    candidates = Player.objects.select_related("team").filter(
        parent_links__parent=parent,
        parent_links__removed_at__isnull=True,
        first_name__iexact=signup.player_first_name.strip(),
        last_name__iexact=signup.player_last_name.strip(),
    )
    if signup.date_of_birth:
        candidates = candidates.filter(date_of_birth=signup.date_of_birth)
    return candidates.first()


@transaction.atomic
def promote_signup_to_roster(signup, created_by, existing_player=None):
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

    existing_player (a confirmed returning player, see find_existing_player)
    is moved to signup.team instead of creating a new Player, keeping its
    photo, gallery, fees and parent links. Its roster positions are kept
    too; the sign-up's positions are only used for a new Player.
    """
    if signup.promoted_player_id or signup.team.is_deleted_placeholder:
        return None

    if existing_player is not None:
        player = existing_player
        player.team = signup.team
        player.save(update_fields=["team"])
    else:
        if not signup.date_of_birth:
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
            parent=signup.responded_by,
            player=player,
            removed_at__isnull=True,
            defaults={"created_by": created_by},
        )
    return player
