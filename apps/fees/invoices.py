"""
Drafting, sending, voiding and settling invoices. An invoice bundles one
parent's open Fees (see Invoice in models.py); it never holds payment state of
its own. Marking one paid just records ordinary Payments on its fees.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ParentPlayerLink
from config.context_processors import GENERAL_CONTACT_EMAIL

from .models import Fee, Invoice, InvoiceLine, Payment

logger = logging.getLogger(__name__)


class InvoiceError(Exception):
    """A rule was broken (shown to the admin as-is)."""


def line_description(fee):
    return f"{fee.player.first_name} {fee.player.last_name}: {fee.description}"


def next_number():
    return (Invoice.objects.aggregate(m=Max("number"))["m"] or 0) + 1


def open_fees():
    """Fees that could go on a new invoice: a player's fee with a balance that isn't on a sent invoice. Fees on a draft count (drafts get rebuilt); so do fees from a void invoice."""
    on_sent = InvoiceLine.objects.filter(invoice__status=Invoice.Status.SENT).values("fee_id")
    fees = (
        Fee.objects.filter(player__isnull=False)
        .exclude(pk__in=on_sent)
        .select_related("player")
        .prefetch_related("payments")
        .order_by("player__last_name", "player__first_name", "due_date", "pk")
    )
    return [fee for fee in fees if fee.balance > 0]


def generate_drafts(due_date, team=None, user=None):
    """
    Drafts one invoice per primary parent from their kids' open fees,
    limited to players on `team` if given. Returns (created, rebuilt,
    without_parent): `without_parent` counts fees skipped because the
    player has no primary parent.

    A parent's existing draft is rebuilt from scratch, keeping its number
    (and keeping fees it already held even if outside the team filter).
    Sent, paid and void invoices are never touched.
    """
    fees = open_fees()
    primary = {
        link.player_id: link.parent_id
        for link in ParentPlayerLink.objects.filter(
            player_id__in={f.player_id for f in fees},
            is_primary=True,
            removed_at__isnull=True,
        )
    }
    by_parent, without_parent = {}, 0
    for fee in fees:
        parent_id = primary.get(fee.player_id)
        if parent_id is None:
            if team is None or fee.player.team_id == team.pk:
                without_parent += 1
            continue
        by_parent.setdefault(parent_id, []).append(fee)

    created = rebuilt = 0
    with transaction.atomic():
        for parent_id, parent_fees in by_parent.items():
            old = Invoice.objects.filter(parent_id=parent_id, status=Invoice.Status.DRAFT).first()
            held = set(old.lines.values_list("fee_id", flat=True)) if old else set()
            chosen = [
                f
                for f in parent_fees
                if team is None or f.player.team_id == team.pk or f.pk in held
            ]
            if not any(team is None or f.player.team_id == team.pk for f in chosen):
                continue  # nothing for this parent within the filter
            number = old.number if old else next_number()
            if old:
                old.delete()
            invoice = Invoice.objects.create(
                parent_id=parent_id, number=number, due_date=due_date, created_by=user
            )
            InvoiceLine.objects.bulk_create(
                InvoiceLine(
                    invoice=invoice, fee=f, description=line_description(f), amount=f.balance
                )
                for f in chosen
            )
            rebuilt += old is not None
            created += old is None
    return created, rebuilt, without_parent


def with_lines():
    return Invoice.objects.select_related("parent").prefetch_related(
        "lines__fee__player", "lines__fee__payments"
    )


def invoice_email(invoice):
    parent = invoice.parent
    body = render_to_string(
        "emails/invoice.txt",
        {
            "invoice": invoice,
            "parent": parent,
            "lines": invoice.lines.all(),
            "total": invoice.total,
            "dashboard_url": settings.SITE_URL + reverse("accounts:dashboard"),
            "contact_email": GENERAL_CONTACT_EMAIL,
        },
    )
    subject = f"Invoice #{invoice.number} from Choice Select"
    return subject, body


def send_invoice(invoice):
    """
    Makes a draft final and emails the parent. Amounts are refreshed to each
    fee's current balance first; fees paid in the meantime drop off. If the
    email fails the exception propagates and the invoice stays a draft.
    """
    with transaction.atomic():
        invoice = with_lines().select_for_update(of=("self",)).get(pk=invoice.pk)
        if invoice.status != Invoice.Status.DRAFT:
            raise InvoiceError("Only a draft can be sent.")
        for line in invoice.lines.all():
            balance = line.fee.balance
            if balance <= 0:
                line.delete()
            else:
                line.description, line.amount = line_description(line.fee), balance
                line.save(update_fields=["description", "amount"])
        invoice = with_lines().get(pk=invoice.pk)
        if not invoice.lines.all():
            raise InvoiceError("Everything on this invoice has been paid, so there is nothing to send.")
        invoice.status = Invoice.Status.SENT
        invoice.sent_at = timezone.now()
        invoice.sent_to_email = invoice.parent.email
        invoice.save(update_fields=["status", "sent_at", "sent_to_email"])
        subject, body = invoice_email(invoice)
        EmailMessage(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [invoice.parent.email],
            reply_to=[GENERAL_CONTACT_EMAIL],
        ).send()  # raising rolls the status change back
    return invoice


def void_invoice(invoice):
    """Cancels a sent invoice that was a mistake; its fees can be invoiced again. A paid one can't be voided."""
    invoice = with_lines().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.SENT or invoice.display_status == "paid":
        raise InvoiceError("Only a sent invoice that hasn't been paid can be voided.")
    invoice.status = Invoice.Status.VOID
    invoice.save(update_fields=["status"])


@transaction.atomic
def mark_paid(invoice, method, paid_at, user):
    """Records one Payment for the remaining balance of each fee on a sent invoice."""
    invoice = with_lines().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.SENT:
        raise InvoiceError("Send the invoice before marking it paid.")
    if invoice.display_status == "paid":
        raise InvoiceError("This invoice is already paid.")
    for line in invoice.lines.all():
        balance = line.fee.balance
        if balance > 0:
            Payment.objects.create(
                fee=line.fee,
                amount=balance,
                method=method,
                paid_at=paid_at,
                recorded_by=user,
                notes=f"Invoice #{invoice.number}",
            )


def summary(invoices):
    """(waiting, paid, late_count) over a list of invoices (lines prefetched)."""
    waiting = paid = Decimal("0.00")
    late = 0
    for inv in invoices:
        status = inv.display_status
        if status == "sent":
            waiting += inv.balance
            late += inv.is_late
        elif status == "paid":
            paid += inv.total
    return waiting, paid, late
