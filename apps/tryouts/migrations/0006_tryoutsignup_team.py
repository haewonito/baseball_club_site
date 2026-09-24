# Hand-written (not `makemigrations`) -- adding a required FK to a table
# with existing rows normally needs an interactive default from Django's
# questioner. There's no real production tryout data yet (this project's
# established pattern this session: local/prod get flushed and reseeded
# freely), so this is applied against an empty table -- a plain NOT NULL
# column addition with no default, which Postgres allows fine when there
# are zero existing rows to violate it.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0005_team_accepting_tryouts_team_is_public'),
        ('tryouts', '0005_alter_tryoutsignup_options_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tryoutsignup',
            name='tryout_year',
        ),
        migrations.RemoveField(
            model_name='tryoutyearsettings',
            name='cutoff_month',
        ),
        migrations.RemoveField(
            model_name='tryoutyearsettings',
            name='cutoff_day',
        ),
        migrations.AddField(
            model_name='tryoutsignup',
            name='team',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tryout_signups',
                to='teams.team',
            ),
        ),
    ]
