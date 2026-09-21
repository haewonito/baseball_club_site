from django.conf import settings
from django.db import models


class Fee(models.Model):
    """
    What's owed. Per player, or team-wide (in which case `player` is
    null and this represents a fee that applies to the whole team --
    admin UI would still need to generate per-player ledger rows or
    handle it as a shared line item, decided at build time).

    No in-house payment processing: if online payment is ever added,
    it goes through a processor (Stripe/Square) rather than storing
    card data here.
    """

    player = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, null=True, blank=True, related_name="fees"
    )
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, null=True, blank=True, related_name="fees"
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
