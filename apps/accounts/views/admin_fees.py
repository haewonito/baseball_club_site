from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.fees.models import FEE_STATUS_LABELS, Fee, FeeReminderSettings, Payment
from apps.fees.reminders import OVERDUE_REMINDER_AFTER_DAYS
from apps.teams.models import Team

from ..forms import FeeAddForm, FeeForm, PlayerPaymentForm
from ..models import Player


@login_required
def admin_fees_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    only_outstanding = request.GET.get("outstanding") == "1"
    fees = (
        Fee.objects.filter(player__isnull=False)
        .select_related("player", "player__team", "reminder")
        .prefetch_related("payments")
        .order_by("due_date", "created_at")
    )

    # One row per player: their unpaid fees and the total still owed.
    by_player = {}
    total_outstanding = 0
    for fee in fees:
        row = by_player.setdefault(
            fee.player_id,
            {"player": fee.player, "open_fees": [], "balance": 0, "overdue": False, "partial": False},
        )
        balance = fee.balance
        if balance > 0:
            total_outstanding += balance
            row["open_fees"].append(fee)
            row["balance"] += balance
            status = fee.status
            row["overdue"] = row["overdue"] or status == "overdue"
            row["partial"] = row["partial"] or status == "partially_paid"

    rows = []
    for row in by_player.values():
        if only_outstanding and not row["open_fees"]:
            continue
        due_dates = [f.due_date for f in row["open_fees"] if f.due_date]
        row["next_due"] = min(due_dates) if due_dates else None
        row["status_label"] = (
            "Overdue" if row["overdue"]
            else "Partially Paid" if row["partial"]
            else "Unpaid" if row["open_fees"]
            else "Paid"
        )
        rows.append(row)
    rows.sort(key=lambda r: (r["player"].last_name.lower(), r["player"].first_name.lower()))

    return render(
        request,
        "accounts/admin_fees_list.html",
        {
            "rows": rows,
            "total_outstanding": total_outstanding,
            "only_outstanding": only_outstanding,
            "reminder_settings": FeeReminderSettings.load(),
            "reminder_after_days": OVERDUE_REMINDER_AFTER_DAYS,
        },
    )


@login_required
@require_POST
def admin_fee_reminders_toggle(request):
    """Flips the club-wide switch for Gus's automatic overdue reminders."""
    if not request.user.is_admin:
        raise PermissionDenied

    settings_row = FeeReminderSettings.load()
    settings_row.enabled = not settings_row.enabled
    settings_row.updated_by = request.user
    settings_row.save()
    messages.success(
        request,
        "Automatic overdue reminders are back on."
        if settings_row.enabled
        else "Automatic overdue reminders are turned off.",
    )
    return redirect("accounts:admin_fees_list")


@login_required
def admin_fee_add(request):
    if not request.user.is_admin:
        raise PermissionDenied

    if request.method == "POST":
        form = FeeAddForm(request.POST)
        if form.is_valid():
            # One full-amount Fee per checked player, not a single shared
            # row and not split -- ordinary per-player Fees, so every other
            # fee/payment view (admin list, parent dashboard, payment
            # history) needs no bulk-fee-aware logic of its own.
            players = list(form.cleaned_data["players"])
            Fee.objects.bulk_create(
                Fee(
                    player=player,
                    description=form.cleaned_data["description"],
                    amount_due=form.cleaned_data["amount_due"],
                    due_date=form.cleaned_data["due_date"],
                    created_by=request.user,
                )
                for player in players
            )
            if len(players) == 1:
                return redirect("accounts:admin_fee_player", player_pk=players[0].pk)
            messages.success(
                request,
                f"Added a ${form.cleaned_data['amount_due']} "
                f"\"{form.cleaned_data['description']}\" fee for {len(players)} players.",
            )
            return redirect("accounts:admin_fees_list")
        selected = set(request.POST.getlist("players"))
    else:
        form = FeeAddForm()
        selected = set()

    players = Player.objects.select_related("team").order_by("last_name", "first_name")
    player_rows = [{"player": p, "checked": str(p.pk) in selected} for p in players]
    teams = Team.objects.filter(is_deleted_placeholder=False, players__isnull=False).distinct().order_by(
        "-season_year", "division"
    )
    return render(
        request,
        "accounts/admin_fee_form.html",
        {"form": form, "heading": "Create a New Fee", "player_rows": player_rows, "teams": teams},
    )


@login_required
def admin_fee_edit(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    fee = get_object_or_404(Fee, pk=pk)
    if request.method == "POST":
        form = FeeForm(request.POST, instance=fee)
        if form.is_valid():
            form.save()
            return redirect("accounts:admin_fee_player", player_pk=fee.player_id)
    else:
        form = FeeForm(instance=fee)
    return render(
        request, "accounts/admin_fee_form.html", {"form": form, "heading": "Edit Fee", "fee": fee}
    )


def _player_fee_context(player, payment_form=None):
    """Unpaid fees plus every payment ever recorded for one player."""
    fees = list(player.fees.select_related("reminder").prefetch_related("payments").order_by("due_date", "created_at"))
    open_fees = [
        {"fee": f, "balance": f.balance, "status_label": FEE_STATUS_LABELS.get(f.status, f.status)}
        for f in fees
        if f.balance > 0
    ]
    payments = sorted(
        (p for f in fees for p in f.payments.all()), key=lambda p: (p.paid_at, p.recorded_at), reverse=True
    )
    if payment_form is None:
        payment_form = PlayerPaymentForm(open_fees=[r["fee"] for r in open_fees])
    return {
        "player": player,
        "open_fees": open_fees,
        "total_balance": sum(r["balance"] for r in open_fees),
        "total_paid": sum(p.amount for p in payments),
        "payments": payments,
        "payment_form": payment_form,
    }


@login_required
def admin_fee_player(request, player_pk):
    if not request.user.is_admin:
        raise PermissionDenied

    player = get_object_or_404(Player.objects.select_related("team"), pk=player_pk)
    return render(request, "accounts/admin_fee_player.html", _player_fee_context(player))


@login_required
@require_POST
def admin_fee_record_payment(request, player_pk):
    if not request.user.is_admin:
        raise PermissionDenied

    player = get_object_or_404(Player.objects.select_related("team"), pk=player_pk)
    open_fees = [f for f in player.fees.prefetch_related("payments") if f.balance > 0]
    form = PlayerPaymentForm(request.POST, open_fees=open_fees)
    if form.is_valid():
        # Earliest due date first; fees with no due date last.
        open_fees.sort(key=lambda f: (f.due_date is None, f.due_date or date.min))
        remaining = form.cleaned_data["amount"]
        for fee in open_fees:
            if remaining <= 0:
                break
            part = min(remaining, fee.balance)
            Payment.objects.create(
                fee=fee,
                amount=part,
                method=form.cleaned_data["method"],
                paid_at=form.cleaned_data["paid_at"],
                notes=form.cleaned_data["notes"],
                recorded_by=request.user,
            )
            remaining -= part
        form = None

    # Rebuild from fresh queries so the new payment is included in balances.
    return render(
        request, "partials/_fee_ledger.html", _player_fee_context(player, payment_form=form)
    )
