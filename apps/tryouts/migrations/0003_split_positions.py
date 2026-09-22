import django.db.models.deletion
from django.db import migrations, models

# Best-effort mapping from things the old free-text `positions` field could
# have contained to the new canonical codes. Covers the canonical codes
# themselves, the old apps.teams.Position codes they replace, and the
# common spelled-out forms. "Pitcher"/"P" and "Outfield"/"OF" are
# deliberately NOT mapped -- there's no way to infer left/right-handed or
# which outfield spot from those, so any such token is left unconverted
# (a note is printed at migration time so an admin can fix it up via the
# new inline on the sign-up admin page).
POSITION_ALIASES = {
    "lp": "LP", "left-handed pitcher": "LP", "left handed pitcher": "LP", "lefty": "LP",
    "rp": "RP", "right-handed pitcher": "RP", "right handed pitcher": "RP", "righty": "RP",
    "c": "C", "catcher": "C",
    "b1": "B1", "1b": "B1", "first base": "B1", "first baseman": "B1", "firstbase": "B1",
    "b2": "B2", "2b": "B2", "second base": "B2", "second baseman": "B2", "secondbase": "B2",
    "b3": "B3", "3b": "B3", "third base": "B3", "third baseman": "B3", "thirdbase": "B3",
    "ss": "SS", "shortstop": "SS", "short stop": "SS",
    "lf": "LF", "left field": "LF", "left fielder": "LF",
    "cf": "CF", "center field": "CF", "center fielder": "CF", "centre field": "CF",
    "rf": "RF", "right field": "RF", "right fielder": "RF",
}


def split_positions_into_rows(apps, schema_editor):
    TryoutSignup = apps.get_model("tryouts", "TryoutSignup")
    TryoutSignupPosition = apps.get_model("tryouts", "TryoutSignupPosition")
    for signup in TryoutSignup.objects.all():
        for token in signup.positions_text.split(","):
            token = token.strip().lower()
            if not token:
                continue
            code = POSITION_ALIASES.get(token)
            if code is None:
                print(
                    f"  [0003_split_positions] couldn't auto-map position "
                    f"{token!r} for signup {signup.pk} ({signup.player_first_name} "
                    f"{signup.player_last_name}) -- add it manually in the admin."
                )
                continue
            TryoutSignupPosition.objects.get_or_create(signup=signup, position=code)


def merge_positions_back(apps, schema_editor):
    """Reverse: join the selected codes back into the old free-text field."""
    TryoutSignup = apps.get_model("tryouts", "TryoutSignup")
    for signup in TryoutSignup.objects.all():
        codes = signup.positions.values_list("position", flat=True)
        signup.positions_text = ", ".join(codes)
        signup.save(update_fields=["positions_text"])


class Migration(migrations.Migration):

    dependencies = [
        ("tryouts", "0002_split_names"),
        ("teams", "0002_canonical_position_list"),
    ]

    operations = [
        # Relax the old field first so it can hold a value again if this
        # migration is ever reversed on a non-empty table (same reason as
        # in 0002_split_names).
        migrations.AlterField(
            model_name="tryoutsignup",
            name="positions",
            field=models.CharField(max_length=100, blank=True, null=True),
        ),
        migrations.RenameField(
            model_name="tryoutsignup",
            old_name="positions",
            new_name="positions_text",
        ),
        migrations.CreateModel(
            name="TryoutSignupPosition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "position",
                    models.CharField(
                        choices=[
                            ("LP", "Left-handed pitcher"),
                            ("RP", "Right-handed pitcher"),
                            ("C", "Catcher"),
                            ("B1", "First baseman"),
                            ("B2", "Second baseman"),
                            ("B3", "Third baseman"),
                            ("SS", "Shortstop"),
                            ("LF", "Left fielder"),
                            ("CF", "Center fielder"),
                            ("RF", "Right fielder"),
                        ],
                        max_length=5,
                    ),
                ),
                (
                    "signup",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="positions",
                        to="tryouts.tryoutsignup",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="tryoutsignupposition",
            constraint=models.UniqueConstraint(
                fields=("signup", "position"), name="unique_signup_position"
            ),
        ),
        migrations.RunPython(split_positions_into_rows, reverse_code=merge_positions_back),
        migrations.RemoveField(
            model_name="tryoutsignup",
            name="positions_text",
        ),
    ]
