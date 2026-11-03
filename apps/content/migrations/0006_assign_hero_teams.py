import random

from django.db import migrations


def assign_random_teams(apps, schema_editor):
    """Banner pictures now link to a team; give the existing ones a random public team (user request 2026-11-03)."""
    HeroImage = apps.get_model("content", "HeroImage")
    Team = apps.get_model("teams", "Team")
    teams = list(Team.objects.filter(is_public=True, is_deleted_placeholder=False))
    if not teams:
        return
    for image in HeroImage.objects.filter(team__isnull=True):
        image.team = random.choice(teams)
        image.save(update_fields=["team"])


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0005_heroimage_team"),
    ]

    operations = [
        migrations.RunPython(assign_random_teams, migrations.RunPython.noop),
    ]
