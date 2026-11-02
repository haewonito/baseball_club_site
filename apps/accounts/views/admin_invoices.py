import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.fees import invoices
from apps.fees.models import Invoice, InvoiceLine

from ..forms import InvoiceDueDateForm, InvoiceGenerateForm, InvoicePaidForm

logger = logging.getLogger(__name__)


@login_required
def admin_invoices_list(request):
    if not request.user.is_admin:
        raise PermissionDenied

    if request.method == "POST":
        form = InvoiceGenerateForm(request.POST)
        if form.is_valid():
            created, rebuilt, without_parent = invoices.generate_drafts(
                form.cleaned_data["due_date"], form.cleaned_data["team"], request.user
            )
            if created or rebuilt:
                messages.success(
                    request,
                    f"Drafted {created} new and rebuilt {rebuilt} invoice drafts. "
                    "Review each one, then send it.",
                )
            else:
                messages.info(request, "No open fees to invoice.")
            if without_parent:
                messages.warning(
                    request,
                    f"{without_parent} fee(s) were skipped because the player has no linked parent.",
                )
            return redirect("accounts:admin_invoices_list")
    else:
        form = InvoiceGenerateForm()

    all_invoices = list(invoices.with_lines())
    waiting, paid, late = invoices.summary(all_invoices)
    return render(
        request,
        "accounts/admin_invoices_list.html",
        {
            "invoices": all_invoices,
            "form": form,
            "waiting": waiting,
            "paid": paid,
            "late": late,
        },
    )


def _get_invoice_or_404(pk):
    return get_object_or_404(invoices.with_lines(), pk=pk)


@login_required
def admin_invoice_detail(request, pk):
    if not request.user.is_admin:
        raise PermissionDenied

    invoice = _get_invoice_or_404(pk)
    return render(
        request,
        "accounts/admin_invoice_detail.html",
        {
            "invoice": invoice,
            "due_form": InvoiceDueDateForm(initial={"due_date": invoice.due_date}),
            "paid_form": InvoicePaidForm(initial={"paid_at": timezone.localdate()}),
        },
    )


def _invoice_action(request, pk, action):
    """Shared by the POST-only invoice buttons; `action(invoice)` raises InvoiceError to refuse."""
    if not request.user.is_admin:
        raise PermissionDenied
    invoice = _get_invoice_or_404(pk)
    try:
        return invoice, action(invoice)
    except invoices.InvoiceError as error:
        messages.error(request, str(error))
        return invoice, None


@login_required
@require_POST
def admin_invoice_due_date(request, pk):
    def action(invoice):
        if invoice.status != Invoice.Status.DRAFT:
            raise invoices.InvoiceError("Only a draft can be changed.")
        form = InvoiceDueDateForm(request.POST)
        if not form.is_valid():
            raise invoices.InvoiceError("Enter a valid due date.")
        invoice.due_date = form.cleaned_data["due_date"]
        invoice.save(update_fields=["due_date"])
        return True

    _invoice_action(request, pk, action)
    return redirect("accounts:admin_invoice_detail", pk=pk)


@login_required
@require_POST
def admin_invoice_remove_line(request, pk, line_id):
    def action(invoice):
        if invoice.status != Invoice.Status.DRAFT:
            raise invoices.InvoiceError("Only a draft can be changed.")
        invoice.lines.filter(pk=line_id).delete()
        if not InvoiceLine.objects.filter(invoice_id=invoice.pk).exists():  # not invoice.lines: prefetched, stale
            invoice.delete()
            return "deleted"
        return True

    _, result = _invoice_action(request, pk, action)
    if result == "deleted":
        messages.success(request, "That was the last line, so the draft was deleted.")
        return redirect("accounts:admin_invoices_list")
    return redirect("accounts:admin_invoice_detail", pk=pk)


@login_required
@require_POST
def admin_invoice_delete(request, pk):
    def action(invoice):
        if invoice.status != Invoice.Status.DRAFT:
            raise invoices.InvoiceError("Only a draft can be deleted. Void a sent invoice instead.")
        invoice.delete()
        return True

    _, result = _invoice_action(request, pk, action)
    if result:
        messages.success(request, "Draft deleted.")
        return redirect("accounts:admin_invoices_list")
    return redirect("accounts:admin_invoice_detail", pk=pk)


@login_required
@require_POST
def admin_invoice_send(request, pk):
    def action(invoice):
        try:
            sent = invoices.send_invoice(invoice)
        except invoices.InvoiceError:
            raise
        except Exception:
            logger.exception("Invoice %s email failed", invoice.pk)
            raise invoices.InvoiceError(
                "The email couldn't be sent, so the invoice is still a draft. Please try again."
            )
        messages.success(request, f"Invoice #{sent.number} sent to {sent.sent_to_email}.")
        return True

    _invoice_action(request, pk, action)
    return redirect("accounts:admin_invoice_detail", pk=pk)


@login_required
@require_POST
def admin_invoice_mark_paid(request, pk):
    def action(invoice):
        form = InvoicePaidForm(request.POST)
        if not form.is_valid():
            raise invoices.InvoiceError("Choose how it was paid and the date.")
        invoices.mark_paid(
            invoice, form.cleaned_data["method"], form.cleaned_data["paid_at"], request.user
        )
        messages.success(request, f"Invoice #{invoice.number} marked paid.")
        return True

    _invoice_action(request, pk, action)
    return redirect("accounts:admin_invoice_detail", pk=pk)


@login_required
@require_POST
def admin_invoice_void(request, pk):
    def action(invoice):
        invoices.void_invoice(invoice)
        messages.success(request, f"Invoice #{invoice.number} voided.")
        return True

    _invoice_action(request, pk, action)
    return redirect("accounts:admin_invoice_detail", pk=pk)
