from django.core.management.base import BaseCommand

from apps.schedule.gamechanger import SyncError, sync_team
from apps.teams.models import Team


class Command(BaseCommand):
    help = (
        "Syncs each team's GameChanger calendar feed into its schedule "
        "(see apps.schedule.gamechanger). Meant to run on a schedule."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team", type=int, help="Only sync the team with this id.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change, without saving anything.",
        )

    def handle(self, *args, team, dry_run, **options):
        teams = Team.objects.filter(is_deleted_placeholder=False).exclude(gamechanger_feed_url="")
        if team:
            teams = teams.filter(pk=team)
        failures = 0
        for t in teams:
            try:
                counts, skipped_titles = sync_team(t, dry_run=dry_run)
            except SyncError as exc:
                failures += 1
                self.stderr.write(f"{t}: FAILED - {exc}")
                continue
            summary = ", ".join(f"{n} {label.replace('_', ' ')}" for label, n in counts.items())
            self.stdout.write(f"{t}{' (dry run)' if dry_run else ''}: {summary}")
            for title in skipped_titles:
                self.stdout.write(f"  skipped (not a practice or game): {title}")
        if not teams:
            self.stdout.write("No teams have a GameChanger calendar link.")
        if failures:
            raise SystemExit(1)
