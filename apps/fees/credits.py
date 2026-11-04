"""Credits: an overpaid fee has a negative balance (see admin_fee_record_payment). Whenever a player
has both a credit and a fee with a balance, the credit is moved onto that fee, with a clear pair of
rows in the payment history (method "Credit applied"): a negative row on the overpaid fee and a
positive row on the fee it pays down. Net money received is unchanged."""
from datetime import date
from decimal import Decimal

from django.utils import timezone

from .models import Payment, PaymentMethod


def apply_credit(player, user=None):
    """Moves the player's credit onto their unpaid fees, earliest due date first. Returns the amount moved."""
    fees = list(player.fees.prefetch_related("payments"))
    balances = {fee.pk: fee.balance for fee in fees}
    sources = [fee for fee in fees if balances[fee.pk] < 0]
    targets = sorted(
        (fee for fee in fees if balances[fee.pk] > 0),
        key=lambda fee: (fee.due_date is None, fee.due_date or date.min),
    )
    moved = Decimal("0")
    today = timezone.localdate()
    for source in sources:
        for target in targets:
            available = -balances[source.pk]
            if available <= 0:
                break
            amount = min(available, balances[target.pk])
            if amount <= 0:
                continue
            for fee, signed, note in (
                (source, -amount, f"Credit moved to {target.description}"),
                (target, amount, f"Credit from {source.description}"),
            ):
                Payment.objects.create(
                    fee=fee,
                    amount=signed,
                    method=PaymentMethod.CREDIT,
                    paid_at=today,
                    notes=note,
                    recorded_by=user,
                )
            balances[source.pk] += amount
            balances[target.pk] -= amount
            moved += amount
    return moved
