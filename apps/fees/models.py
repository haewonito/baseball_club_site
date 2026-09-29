from django.conf import settings
from django.db import models

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
    sent_to_email = models.EmailField()
    balance_at_send = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "Overdue Fee Reminder"
        verbose_name_plural = "Overdue Fee Reminders"

    def __str__(self):
        return f"Reminder for {self.fee} sent {self.sent_at:%Y-%m-%d}"
