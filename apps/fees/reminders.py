"""
Automated overdue-fee reminders from "Gus", the club's automated
assistant. Run once a day by `manage.py send_fee_reminders` (a Railway
cron service in production -- see CLAUDE.md).

A fee gets one reminder, ever, once it's more than
OVERDUE_REMINDER_AFTER_DAYS past its due date with a balance left, sent
to the player's primary parent (ParentPlayerLink.is_primary). Each send is
recorded as a FeeReminder, which is what the admin fees pages show.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ParentPlayerLink
from config.context_processors import GENERAL_CONTACT_EMAIL

from .models import Fee, FeeReminder, FeeReminderSettings

logger = logging.getLogger(__name__)

ASSISTANT_NAME = "Gus"

# "More than 2 days overdue": a fee due Oct 1 gets its reminder on Oct 4.
OVERDUE_REMINDER_AFTER_DAYS = 2

# Resend's free plan allows 100 emails/day, shared with try-out emails.
# Anything over this waits for the next day's run.
DEFAULT_DAILY_LIMIT = 50


def fees_needing_reminder(today=None):
    """
    (fee, primary_link) pairs that are due a reminder today, oldest due
    date first. Fees with no due date, no balance, an earlier reminder, or
    a player with no primary parent are skipped.
    """
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=OVERDUE_REMINDER_AFTER_DAYS)
    fees = (
        Fee.objects.filter(
            player__isnull=False,
            due_date__isnull=False,
            due_date__lt=cutoff,
            reminder__isnull=True,
        )
        .select_related("player")
        .prefetch_related("payments")
        .order_by("due_date", "pk")
    )
    primary_links = {
        link.player_id: link
        for link in ParentPlayerLink.objects.filter(
            player_id__in={fee.player_id for fee in fees},
            is_primary=True,
            removed_at__isnull=True,
        ).select_related("parent")
    }
    pairs = []
    for fee in fees:
        link = primary_links.get(fee.player_id)
        if fee.balance > 0 and link is not None:
            pairs.append((fee, link))
    return pairs


def send_fee_reminder(fee, link):
    """Sends one reminder and records it. Raises if the send fails (nothing is recorded then)."""
    parent, player = link.parent, fee.player
    body = render_to_string(
        "emails/fee_overdue_reminder.txt",
        {
            "assistant_name": ASSISTANT_NAME,
            "parent": parent,
            "player": player,
            "fee": fee,
            "amount_paid": fee.amount_paid,
            "balance": fee.balance,
            "payments_url": settings.SITE_URL
            + reverse("accounts:parent_player_payments", args=[player.pk]),
            "contact_email": GENERAL_CONTACT_EMAIL,
        },
    )
    subject = f"Friendly reminder: {player.first_name}'s {fee.description} balance"
    EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [parent.email],
        reply_to=[GENERAL_CONTACT_EMAIL],
    ).send()
    return FeeReminder.objects.create(
        fee=fee,
        sent_to=parent,
        sent_to_email=parent.email,
        balance_at_send=fee.balance,
    )


def send_fee_reminders(limit=DEFAULT_DAILY_LIMIT, dry_run=False, today=None):
    """
    Sends today's reminders, up to `limit`. Returns (sent, failed, pending)
    lists of (fee, link); `pending` is what's left over the limit (or
    everything, on a dry run). One failed send is logged and doesn't stop
    the rest; it'll be retried tomorrow.
    """
    if not FeeReminderSettings.reminders_enabled():
        # The admin's club-wide switch is off: nothing goes out, and nothing
        # is recorded, so fees stay eligible for when it's turned back on.
        return [], [], []
    pairs = fees_needing_reminder(today)
    if dry_run:
        return [], [], pairs
    sent, failed = [], []
    for fee, link in pairs[:limit]:
        try:
            send_fee_reminder(fee, link)
        except Exception:
            logger.exception("Overdue fee reminder failed for fee %s", fee.pk)
            failed.append((fee, link))
        else:
            sent.append((fee, link))
    return sent, failed, pairs[limit:]
