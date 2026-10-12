import datetime
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ParentPlayerLink, Player, User
from apps.teams.models import Team

from . import invoices
from .models import Fee, Invoice, Payment

DUE = datetime.date(2030, 1, 15)


def make_team(name, division):
    return Team.objects.create(name=name, division=division, season_year=2030)


class InvoiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin@example.com", "pw")
        cls.team10, cls.team12 = make_team("10U", "10U"), make_team("12U", "12U")

    def make_family(self, email, kids, team=None):
        parent = User.objects.create_user(email, "pw", first_name="Pat", last_name=email[:3])
        players = []
        for name in kids:
            player = Player.objects.create(
                first_name=name, last_name="Kid", date_of_birth="2016-01-01", team=team or self.team10
            )
            ParentPlayerLink.objects.create(parent=parent, player=player)
            players.append(player)
        return parent, players

    def fee(self, player, amount="100.00", description="Dues", due=DUE):
        return Fee.objects.create(
            player=player, description=description, amount_due=Decimal(amount), due_date=due
        )

    def pay(self, fee, amount):
        return Payment.objects.create(
            fee=fee, amount=Decimal(amount), method="cash", paid_at=timezone.localdate()
        )


class GenerateTests(InvoiceTestCase):
    def test_one_draft_per_primary_parent_with_a_line_per_fee(self):
        parent, (a, b) = self.make_family("one@example.com", ["Ann", "Bo"])
        self.fee(a)
        self.fee(b, "50.00")
        created, rebuilt, without_parent = invoices.generate_drafts(DUE, None, self.admin)
        self.assertEqual((created, rebuilt, without_parent), (1, 0, 0))
        invoice = invoices.with_lines().get()
        self.assertEqual(invoice.parent, parent)
        self.assertEqual(invoice.total, Decimal("150.00"))
        self.assertEqual(invoice.status, Invoice.Status.DRAFT)

    def test_only_the_primary_parent_is_invoiced(self):
        parent, (kid,) = self.make_family("one@example.com", ["Ann"])
        second = User.objects.create_user("two@example.com", "pw")
        ParentPlayerLink.objects.create(parent=second, player=kid)
        self.fee(kid)
        invoices.generate_drafts(DUE)
        self.assertEqual(Invoice.objects.get().parent, parent)

    def test_numbers_count_up(self):
        for i in range(3):
            _, (kid,) = self.make_family(f"p{i}@example.com", [f"K{i}"])
            self.fee(kid)
        invoices.generate_drafts(DUE)
        self.assertEqual(sorted(Invoice.objects.values_list("number", flat=True)), [1, 2, 3])

    def test_paid_fees_and_fees_without_a_player_are_skipped(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        paid = self.fee(kid)
        self.pay(paid, "100.00")
        Fee.objects.create(team=self.team10, description="Team", amount_due=5, due_date=DUE)
        self.assertEqual(invoices.generate_drafts(DUE), (0, 0, 0))

    def test_a_player_without_a_parent_is_reported(self):
        orphan = Player.objects.create(
            first_name="Or", last_name="Phan", date_of_birth="2016-01-01", team=self.team10
        )
        self.fee(orphan)
        self.assertEqual(invoices.generate_drafts(DUE), (0, 0, 1))

    def test_a_partly_paid_fee_is_invoiced_for_its_balance(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.pay(self.fee(kid), "40.00")
        invoices.generate_drafts(DUE)
        self.assertEqual(invoices.with_lines().get().total, Decimal("60.00"))

    def test_generating_again_rebuilds_the_draft_and_keeps_its_number(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee(kid)
        invoices.generate_drafts(DUE)
        first = Invoice.objects.get()
        self.fee(kid, "25.00", "Shirt")
        self.assertEqual(invoices.generate_drafts(DUE), (0, 1, 0))
        rebuilt = invoices.with_lines().get()
        self.assertEqual(rebuilt.number, first.number)
        self.assertEqual(rebuilt.total, Decimal("125.00"))

    def test_generating_leaves_sent_invoices_alone_and_does_not_reinvoice_their_fees(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee(kid)
        invoices.generate_drafts(DUE)
        invoices.send_invoice(Invoice.objects.get())
        self.assertEqual(invoices.generate_drafts(DUE), (0, 0, 0))
        self.assertEqual(Invoice.objects.count(), 1)
        self.fee(kid, "25.00", "Shirt")  # a new fee gets its own invoice
        self.assertEqual(invoices.generate_drafts(DUE), (1, 0, 0))
        self.assertEqual(sorted(Invoice.objects.values_list("number", flat=True)), [1, 2])

    def test_team_filter_only_drafts_that_teams_players(self):
        _, (a,) = self.make_family("one@example.com", ["Ann"], self.team10)
        _, (b,) = self.make_family("two@example.com", ["Bo"], self.team12)
        self.fee(a)
        self.fee(b)
        invoices.generate_drafts(DUE, self.team12)
        self.assertEqual(list(Invoice.objects.values_list("parent__email", flat=True)), ["two@example.com"])

    def test_team_filter_keeps_other_team_fees_already_on_the_parents_draft(self):
        parent, (a,) = self.make_family("one@example.com", ["Ann"], self.team10)
        b = Player.objects.create(
            first_name="Bo", last_name="Kid", date_of_birth="2016-01-01", team=self.team12
        )
        ParentPlayerLink.objects.create(parent=parent, player=b)
        self.fee(a)
        self.fee(b)
        invoices.generate_drafts(DUE)  # both kids, one draft
        invoices.generate_drafts(DUE, self.team12)
        self.assertEqual(invoices.with_lines().get().lines.count(), 2)

    def test_a_void_invoices_fees_can_be_invoiced_again(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee(kid)
        invoices.generate_drafts(DUE)
        invoices.void_invoice(invoices.send_invoice(Invoice.objects.get()))
        self.assertEqual(invoices.generate_drafts(DUE), (1, 0, 0))


class SendPayVoidTests(InvoiceTestCase):
    def setUp(self):
        self.parent, (self.kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee_row = self.fee(self.kid)
        invoices.generate_drafts(DUE)
        self.invoice = Invoice.objects.get()

    def test_sending_emails_the_parent_and_makes_it_sent(self):
        invoices.send_invoice(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.SENT)
        self.assertEqual(self.invoice.sent_to_email, "one@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["one@example.com"])
        self.assertIn("$100.00", mail.outbox[0].body)
        self.assertIn("Ann Kid: Dues", mail.outbox[0].body)

    def test_a_sent_invoice_cannot_be_sent_again(self):
        invoices.send_invoice(self.invoice)
        with self.assertRaises(invoices.InvoiceError):
            invoices.send_invoice(self.invoice)

    def test_a_failed_email_leaves_a_draft(self):
        from unittest import mock

        with mock.patch("apps.fees.invoices.EmailMessage.send", side_effect=OSError):
            with self.assertRaises(OSError):
                invoices.send_invoice(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.DRAFT)
        self.assertIsNone(self.invoice.sent_at)

    def test_sending_refreshes_amounts_and_drops_fees_paid_since(self):
        paid_since = self.fee(self.kid, "30.00", "Shirt")
        invoices.generate_drafts(DUE)
        self.pay(paid_since, "30.00")
        self.pay(self.fee_row, "40.00")
        sent = invoices.send_invoice(Invoice.objects.get())
        self.assertEqual(sent.total, Decimal("60.00"))
        self.assertEqual(sent.lines.count(), 1)

    def test_a_draft_with_nothing_left_to_pay_cannot_be_sent(self):
        self.pay(self.fee_row, "100.00")
        with self.assertRaises(invoices.InvoiceError):
            invoices.send_invoice(self.invoice)
        self.assertEqual(len(mail.outbox), 0)

    def test_status_follows_the_fee_balances(self):
        sent = invoices.send_invoice(self.invoice)
        self.assertEqual(sent.display_status, "sent")
        self.pay(self.fee_row, "40.00")
        self.assertEqual(invoices.with_lines().get().balance, Decimal("60.00"))
        self.assertEqual(invoices.with_lines().get().display_status, "sent")
        self.pay(self.fee_row, "60.00")  # recorded on the fee page, not the invoice
        self.assertEqual(invoices.with_lines().get().display_status, "paid")

    def test_late_means_sent_unpaid_and_past_due(self):
        self.assertFalse(invoices.with_lines().get().is_late)  # draft
        Invoice.objects.filter(pk=self.invoice.pk).update(
            due_date=timezone.localdate() - datetime.timedelta(days=1)
        )
        invoices.send_invoice(self.invoice)
        self.assertTrue(invoices.with_lines().get().is_late)
        self.pay(self.fee_row, "100.00")
        self.assertFalse(invoices.with_lines().get().is_late)

    def test_mark_paid_records_a_payment_per_fee_with_the_balance(self):
        extra = self.fee(self.kid, "30.00", "Shirt")
        invoices.generate_drafts(DUE)
        self.pay(extra, "10.00")
        invoices.send_invoice(Invoice.objects.get())
        invoices.mark_paid(Invoice.objects.get(), "venmo", datetime.date(2030, 1, 2), self.admin)
        self.assertEqual(invoices.with_lines().get().display_status, "paid")
        payment = Payment.objects.get(fee=extra, method="venmo")
        self.assertEqual(payment.amount, Decimal("20.00"))
        self.assertEqual(payment.recorded_by, self.admin)
        self.assertEqual(payment.notes, f"Invoice #{self.invoice.number}")

    def test_a_draft_or_paid_invoice_cannot_be_marked_paid(self):
        with self.assertRaises(invoices.InvoiceError):
            invoices.mark_paid(self.invoice, "cash", DUE, self.admin)
        invoices.send_invoice(self.invoice)
        invoices.mark_paid(self.invoice, "cash", DUE, self.admin)
        with self.assertRaises(invoices.InvoiceError):
            invoices.mark_paid(self.invoice, "cash", DUE, self.admin)

    def test_void_only_a_sent_unpaid_invoice(self):
        with self.assertRaises(invoices.InvoiceError):
            invoices.void_invoice(self.invoice)  # draft
        invoices.send_invoice(self.invoice)
        invoices.mark_paid(self.invoice, "cash", DUE, self.admin)
        with self.assertRaises(invoices.InvoiceError):
            invoices.void_invoice(self.invoice)  # paid

    def test_summary_totals(self):
        invoices.send_invoice(self.invoice)
        _, (kid2,) = self.make_family("two@example.com", ["Bo"])
        self.fee(kid2, "50.00", due=DUE)
        invoices.generate_drafts(DUE)
        second = Invoice.objects.get(parent__email="two@example.com")
        invoices.send_invoice(second)
        invoices.mark_paid(second, "cash", DUE, self.admin)
        Invoice.objects.filter(pk=self.invoice.pk).update(
            due_date=timezone.localdate() - datetime.timedelta(days=1)
        )
        waiting, paid, late = invoices.summary(list(invoices.with_lines()))
        self.assertEqual((waiting, paid, late), (Decimal("100.00"), Decimal("50.00"), 1))


# The test run has no collectstatic manifest, so pages that use {% static %} need plain storage.
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class InvoiceViewTests(InvoiceTestCase):
    def test_admin_only(self):
        parent, _ = self.make_family("one@example.com", ["Ann"])
        url = reverse("accounts:admin_invoices_list")
        self.assertEqual(self.client.get(url).status_code, 302)  # login
        self.client.force_login(parent)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"due_date": "2030-01-15"}).status_code, 403)

    def test_generate_review_send_and_pay_through_the_pages(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee(kid)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_invoices_list"), {"team": "", "due_date": "2030-01-15"}
        )
        self.assertRedirects(response, reverse("accounts:admin_invoices_list"))
        invoice = Invoice.objects.get()
        page = self.client.get(reverse("accounts:admin_invoice_detail", args=[invoice.pk]))
        self.assertContains(page, "Send invoice")
        self.client.post(reverse("accounts:admin_invoice_due_date", args=[invoice.pk]), {"due_date": "2030-02-01"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.due_date, datetime.date(2030, 2, 1))
        self.client.post(reverse("accounts:admin_invoice_send", args=[invoice.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.SENT)
        # A sent invoice is locked.
        line = invoice.lines.get()
        self.client.post(reverse("accounts:admin_invoice_remove_line", args=[invoice.pk, line.pk]))
        self.client.post(reverse("accounts:admin_invoice_delete", args=[invoice.pk]))
        self.client.post(reverse("accounts:admin_invoice_due_date", args=[invoice.pk]), {"due_date": "2031-01-01"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.due_date, datetime.date(2030, 2, 1))
        self.client.post(
            reverse("accounts:admin_invoice_mark_paid", args=[invoice.pk]),
            {"method": "check", "paid_at": "2030-01-20"},
        )
        self.assertEqual(invoices.with_lines().get().display_status, "paid")

    def test_removing_the_last_line_deletes_the_draft(self):
        _, (kid,) = self.make_family("one@example.com", ["Ann"])
        self.fee(kid)
        invoices.generate_drafts(DUE)
        invoice = Invoice.objects.get()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("accounts:admin_invoice_remove_line", args=[invoice.pk, invoice.lines.get().pk])
        )
        self.assertFalse(Invoice.objects.exists())
        self.assertTrue(Fee.objects.exists())
