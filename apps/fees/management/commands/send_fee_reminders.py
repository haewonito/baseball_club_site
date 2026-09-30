from django.core.management.base import BaseCommand

from apps.fees.models import FeeReminderSettings
from apps.fees.reminders import DEFAULT_DAILY_LIMIT, send_fee_reminders


class Command(BaseCommand):
    help = (
        "Emails the primary parent once for each fee more than 2 days overdue "
        "(see apps.fees.reminders). Meant to run once a day."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List who would get a reminder, without sending or recording anything.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_DAILY_LIMIT,
            help=f"Most reminders to send this run (default {DEFAULT_DAILY_LIMIT}); the rest wait a day.",
        )

    def handle(self, *args, dry_run, limit, **options):
        if not FeeReminderSettings.reminders_enabled():
            self.stdout.write("Automatic fee reminders are turned off (Fees & Payments page); nothing sent.")
            return
        sent, failed, pending = send_fee_reminders(limit=limit, dry_run=dry_run)

        def describe(fee, link):
            return (
                f"{fee.player} / {fee.description} (due {fee.due_date}, "
                f"balance ${fee.balance}) -> {link.parent.email}"
            )

        if dry_run:
            self.stdout.write(f"Dry run: {len(pending)} reminder(s) would be sent.")
            for fee, link in pending:
                self.stdout.write(f"  {describe(fee, link)}")
            return

        for fee, link in sent:
            self.stdout.write(f"Sent: {describe(fee, link)}")
        for fee, link in failed:
            self.stderr.write(f"FAILED (will retry tomorrow): {describe(fee, link)}")
        self.stdout.write(
            f"{len(sent)} sent, {len(failed)} failed, {len(pending)} left for tomorrow (over the limit)."
        )
