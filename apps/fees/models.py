from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

# Fee.status is a plain Python property, not a `choices` field, so there's
# no model-level get_status_display() -- this is the one shared mapping
# for it, used anywhere a fee's status needs a human label (admin fees
# list, the admin-tier player detail page).
FEE_STATUS_LABELS = {
    "paid": "Paid",
    "partially_paid": "Partially Paid",
    "overdue": "Overdue",
    "unpaid": "Unpaid",
}


class Fee(models.Model):
    """
    What's owed. Per player, or team-wide via the `team` field -- but a
    team-wide Fee row is only ever a transient input, never actually
    persisted as such: apps.accounts.views.admin_fee_add fans it out into
    one full-amount (not split) Fee per current player on that team at
    creation time, so every other fee/payment view only ever deals in
    ordinary per-player rows.

    No in-house payment processing: if online payment is ever added,
    it goes through a processor (Stripe/Square) rather than storing
    card data here.
    """

    player = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, null=True, blank=True, related_name="fees"
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="fees",
        limit_choices_to={"is_deleted_placeholder": False},
    )
    description = models.CharField(max_length=150)  # e.g. "2027 season registration"
    amount_due = models.DecimalField(max_digits=8, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    @property
    def amount_paid(self):
        return sum(p.amount for p in self.payments.all())

    @property
    def balance(self):
        return self.amount_due - self.amount_paid

    @property
    def status(self):
        if self.balance <= 0:
            return "paid"
        if self.amount_paid > 0:
            return "partially_paid"
        if self.due_date and self.due_date < self._today():
            return "overdue"
        return "unpaid"

    @staticmethod
    def _today():
        from datetime import date

        return date.today()

    def __str__(self):
        return f"{self.description} - {self.player or self.team}"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CHECK = "check", "Check"
    VENMO = "venmo", "Venmo"
    OTHER = "other", "Other"


class Payment(models.Model):
    """
    A payment recorded against a Fee, manually entered by an admin.
    """

    fee = models.ForeignKey(Fee, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    paid_at = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.amount} on {self.paid_at} for {self.fee}"


class FeeReminder(models.Model):
    """
    One automated overdue-payment reminder ("Gus", apps.fees.reminders),
    sent to the player's primary parent. At most one per fee, ever (the
    one-to-one): the club doesn't want repeat reminders. Also what the
    admin fees pages show as "Reminder sent". Written only after the email
    actually went out, so a failed send is retried on the next daily run.
    """

    fee = models.OneToOneField(Fee, on_delete=models.CASCADE, related_name="reminder")
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # Snapshots, so the record still reads right after the user's email
    # changes or more payments come in.
    sent_to_email = models.EmailField(blank=True)
    balance_at_send = models.DecimalField(max_digits=8, decimal_places=2)
    # False = no email went out: the fee was already overdue when Gus
    # started (fees migration 0004, the user's choice), so it's marked as
    # reminded to keep him from emailing old balances.
    was_sent = models.BooleanField(default=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "Overdue Fee Reminder"
        verbose_name_plural = "Overdue Fee Reminders"

    def __str__(self):
        return f"Reminder for {self.fee} sent {self.sent_at:%Y-%m-%d}"


class FeeReminderSettings(models.Model):
    """
    Singleton (one row, made on first use): the club-wide on/off switch for
    Gus's automated overdue reminders. Off means `send_fee_reminders` sends
    nothing at all; it is not per fee. Flipped by an admin from the fees
    page (accounts.admin_fee_reminders_toggle).
    """

    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Fee Reminder Settings"
        verbose_name_plural = "Fee Reminder Settings"

    def __str__(self):
        return f"Automatic fee reminders: {'on' if self.enabled else 'off'}"

    @classmethod
    def load(cls):
        return cls.objects.first() or cls.objects.create()

    @classmethod
    def reminders_enabled(cls):
        row = cls.objects.first()
        return row.enabled if row else True


class Invoice(models.Model):
    """
    A bundle of one parent's open Fees, emailed to them as one request for
    payment (apps.fees.invoices). It owns no money state: the Fees and their
    Payments stay the only record of what's owed and what was paid. So
    "Paid" is not stored: a sent invoice shows as paid once every fee on it
    has no balance, whether payments were recorded on the fee pages or with
    the invoice's "Mark paid" button (which just records ordinary Payments).

    Stored status is draft -> sent, or void. A draft is the app's suggestion
    for the admin to review; sending makes its lines final.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VOID = "void", "Void"

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices"
    )
    # Counts up club-wide.
    number = models.PositiveIntegerField(unique=True)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_to_email = models.EmailField(blank=True)  # snapshot, like FeeReminder

    class Meta:
        ordering = ["-number"]

    def __str__(self):
        return f"Invoice {self.number}"

    # The properties below read self.lines -> fee -> payments; prefetch
    # "lines__fee__payments" on any list, as with Fee.balance.

    @property
    def total(self):
        """What was asked for: the lines' amounts (their balances when drafted or sent)."""
        return sum((line.amount for line in self.lines.all()), Decimal("0.00"))

    @property
    def balance(self):
        """What's still owed on those fees right now."""
        return sum((max(line.fee.balance, 0) for line in self.lines.all()), Decimal("0.00"))

    @property
    def display_status(self):
        if self.status == self.Status.SENT and self.balance <= 0:
            return "paid"
        return self.status

    @property
    def is_late(self):
        return self.display_status == "sent" and self.due_date < timezone.localdate()

    @property
    def display_status_label(self):
        if self.is_late:
            return "Late"
        if self.display_status == "paid":
            return "Paid"
        return self.get_status_display()


class InvoiceLine(models.Model):
    """One fee on an invoice. `description`/`amount` are snapshots (the fee's balance when drafted, refreshed when sent)."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    fee = models.ForeignKey(Fee, on_delete=models.PROTECT, related_name="invoice_lines")
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ["fee__player__last_name", "fee__player__first_name", "fee__due_date", "id"]

    def __str__(self):
        return f"{self.description}: {self.amount}"
