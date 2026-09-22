from django.db import migrations, models


def split_full_names(apps, schema_editor):
    """
    Backfill player_first_name/last_name and parent_first_name/last_name
    from the old single full-name fields, for any rows that existed before
    this migration. Splits on the last space: everything before it is the
    first name, the last token is the last name. A name with no space
    (e.g. a single mononym) lands entirely in the first-name field.
    """
    TryoutSignup = apps.get_model("tryouts", "TryoutSignup")
    for signup in TryoutSignup.objects.all():
        player_first, _, player_last = signup.player_name.rpartition(" ")
        signup.player_first_name = player_first or signup.player_name
        signup.player_last_name = player_last if player_first else ""

        parent_first, _, parent_last = signup.parent_name.rpartition(" ")
        signup.parent_first_name = parent_first or signup.parent_name
        signup.parent_last_name = parent_last if parent_first else ""

        signup.save(
            update_fields=[
                "player_first_name",
                "player_last_name",
                "parent_first_name",
                "parent_last_name",
            ]
        )


def merge_full_names(apps, schema_editor):
    """Reverse: recombine first/last back into the single full-name fields."""
    TryoutSignup = apps.get_model("tryouts", "TryoutSignup")
    for signup in TryoutSignup.objects.all():
        signup.player_name = f"{signup.player_first_name} {signup.player_last_name}".strip()
        signup.parent_name = f"{signup.parent_first_name} {signup.parent_last_name}".strip()
        signup.save(update_fields=["player_name", "parent_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("tryouts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tryoutsignup",
            name="player_first_name",
            field=models.CharField(max_length=100, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tryoutsignup",
            name="player_last_name",
            field=models.CharField(max_length=100, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tryoutsignup",
            name="parent_first_name",
            field=models.CharField(max_length=100, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tryoutsignup",
            name="parent_last_name",
            field=models.CharField(max_length=100, default=""),
            preserve_default=False,
        ),
        # Relax the old fields to nullable *before* removing them, and only
        # tighten them back to NOT NULL *after* RunPython's reverse has
        # repopulated them, below. Otherwise reversing this migration on a
        # non-empty table fails: RemoveField's reverse (AddField) would try
        # to recreate a NOT NULL column with no data to fill it, and
        # Postgres rejects that.
        migrations.AlterField(
            model_name="tryoutsignup",
            name="player_name",
            field=models.CharField(max_length=150, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="tryoutsignup",
            name="parent_name",
            field=models.CharField(max_length=150, blank=True, null=True),
        ),
        migrations.RunPython(split_full_names, reverse_code=merge_full_names),
        migrations.RemoveField(
            model_name="tryoutsignup",
            name="player_name",
        ),
        migrations.RemoveField(
            model_name="tryoutsignup",
            name="parent_name",
        ),
    ]
