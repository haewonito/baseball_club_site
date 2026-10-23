from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .emails import make_verification_token
from .models import Role, User

REGISTER_DATA = {
    "first_name": "Pat",
    "last_name": "Lee",
    "email": "pat@example.com",
    "phone": "555-0100",
    "password1": "a-Long-pass-123",
    "password2": "a-Long-pass-123",
}


# The test run has no collectstatic manifest, so pages that use {% static %} need plain storage.
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class RegistrationTests(TestCase):
    def register(self, **extra):
        return self.client.post(reverse("accounts:register"), {**REGISTER_DATA, **extra})

    def test_register_creates_unverified_prospective_parent_and_sends_link(self):
        response = self.register(info_emails_opt_in="on")
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="pat@example.com")
        self.assertFalse(user.email_verified)
        self.assertTrue(user.is_prospective_parent)
        self.assertFalse(user.has_role(Role.PARENT))
        self.assertTrue(user.info_emails_opt_in)
        self.assertIsNotNone(user.info_emails_opt_in_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/verify/", mail.outbox[0].body)

    def test_opt_in_is_off_unless_ticked(self):
        self.register()
        user = User.objects.get(email="pat@example.com")
        self.assertFalse(user.info_emails_opt_in)
        self.assertIsNone(user.info_emails_opt_in_at)

    def test_cannot_log_in_until_verified(self):
        self.register()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pat@example.com", "password": "a-Long-pass-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].unverified)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_link_enables_login(self):
        self.register()
        user = User.objects.get(email="pat@example.com")
        response = self.client.get(reverse("accounts:verify_email", args=[make_verification_token(user)]))
        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pat@example.com", "password": "a-Long-pass-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_bad_and_expired_tokens_are_rejected(self):
        self.register()
        user = User.objects.get(email="pat@example.com")
        response = self.client.get(reverse("accounts:verify_email", args=["garbage"]))
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")
        token = make_verification_token(user)
        with mock.patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 4 * 86400):
            response = self.client.get(reverse("accounts:verify_email", args=[token]))
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")
        user.refresh_from_db()
        self.assertFalse(user.email_verified)

    def test_link_dies_if_email_changed(self):
        self.register()
        user = User.objects.get(email="pat@example.com")
        token = make_verification_token(user)
        user.email = "other@example.com"
        user.save()
        response = self.client.get(reverse("accounts:verify_email", args=[token]))
        self.assertTemplateUsed(response, "accounts/verify_email_invalid.html")

    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user(email="pat@example.com", password="x")
        response = self.register(email="PAT@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_resend_is_throttled_and_never_reveals_accounts(self):
        self.register()
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(reverse("accounts:resend_verification"), {"email": "pat@example.com"})
        self.assertEqual(len(mail.outbox), 1)  # sent seconds ago
        User.objects.update(verification_sent_at=timezone.now() - timedelta(minutes=5))
        self.client.post(reverse("accounts:resend_verification"), {"email": "pat@example.com"})
        self.assertEqual(len(mail.outbox), 2)
        response = self.client.post(reverse("accounts:resend_verification"), {"email": "nobody@example.com"})
        self.assertEqual(response.context["sent_to"], "nobody@example.com")
        self.assertEqual(len(mail.outbox), 2)

    def test_dashboard_redirects_prospective_parent(self):
        self.register()
        User.objects.update(email_verified=True)
        self.client.login(email="pat@example.com", password="a-Long-pass-123")
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(response, reverse("accounts:dashboard_prospect"))


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class ProspectivePlayerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.teams.models import Team
        from apps.tryouts.models import TryoutPoster

        cls.team = Team.objects.create(name="11U", season_year=2027, accepting_tryouts=True)
        TryoutPoster.objects.create(is_active=True, image="x.jpg")
        cls.user = User.objects.create_user(
            email="pat@example.com", password="pw-12345-long", first_name="Pat", last_name="Lee"
        )

    def signup_data(self, **extra):
        return {
            "team": self.team.pk,
            "player_first_name": "sam",
            "player_last_name": "lee",
            "date_of_birth": "2015-05-01",
            "positions": ["C", "SS"],
            "years_experience": "3",
            "parent_first_name": "Pat",
            "parent_last_name": "Lee",
            "parent_phone": "555-0100",
            "parent_email": "pat@example.com",
            **extra,
        }

    def test_logged_in_signup_links_account_and_saves_kid(self):
        from apps.tryouts.models import TryoutSignup

        self.client.force_login(self.user)
        response = self.client.post(reverse("tryouts:signup"), self.signup_data(save_player="on"))
        self.assertRedirects(response, reverse("tryouts:signup_success"))
        signup = TryoutSignup.objects.get()
        self.assertEqual(signup.user, self.user)
        kid = self.user.prospective_players.get()
        self.assertEqual(signup.prospective_player, kid)
        self.assertEqual(kid.full_name, "Sam Lee")
        self.assertEqual(sorted(p.position for p in kid.positions.all()), ["C", "SS"])

    def test_not_saved_unless_ticked(self):
        self.client.force_login(self.user)
        self.client.post(reverse("tryouts:signup"), self.signup_data())
        self.assertFalse(self.user.prospective_players.exists())

    def test_saved_kid_prefills_and_is_updated(self):
        from apps.tryouts.models import ProspectivePlayer, ProspectivePlayerPosition

        kid = ProspectivePlayer.objects.create(
            user=self.user, first_name="Sam", last_name="Lee", date_of_birth="2015-05-01"
        )
        ProspectivePlayerPosition.objects.create(prospect=kid, position="LF")
        self.client.force_login(self.user)
        response = self.client.get(reverse("tryouts:signup"), {"kid": kid.pk})
        form = response.context["form"]
        self.assertEqual(form.initial["player_first_name"], "Sam")
        self.assertEqual(form.initial["positions"], ["LF"])
        self.client.post(
            reverse("tryouts:signup"), self.signup_data(prospective_player=kid.pk, years_experience="5")
        )
        kid.refresh_from_db()
        self.assertEqual(kid.years_experience, 5)
        self.assertEqual(self.user.prospective_players.count(), 1)

    def test_cannot_use_someone_elses_kid(self):
        from apps.tryouts.models import ProspectivePlayer, TryoutSignup

        other = User.objects.create_user(email="o@example.com", password="x")
        kid = ProspectivePlayer.objects.create(
            user=other, first_name="Al", last_name="Roe", date_of_birth="2015-01-01"
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("tryouts:signup"), self.signup_data(prospective_player=kid.pk)
        )
        self.assertEqual(response.status_code, 200)  # form error, not saved
        self.assertFalse(TryoutSignup.objects.exists())
        self.assertEqual(self.client.get(reverse("accounts:prospect_player_edit", args=[kid.pk])).status_code, 404)

    def test_guest_signup_still_works_and_shows_on_dashboard_by_email(self):
        from apps.tryouts.models import TryoutSignup

        # Another account's email isn't taken: use a fresh one.
        data = self.signup_data(parent_email="guest@example.com")
        response = self.client.post(reverse("tryouts:signup"), data)
        self.assertRedirects(response, reverse("tryouts:signup_success"))
        self.assertIsNone(TryoutSignup.objects.get().user)
        guest = User.objects.create_user(email="guest@example.com", password="x")
        self.client.force_login(guest)
        response = self.client.get(reverse("accounts:dashboard_prospect"))
        self.assertEqual(len(response.context["signups"]), 1)

    def test_add_edit_delete_kid_from_dashboard(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:prospect_player_add")).status_code, 200)
        self.client.post(
            reverse("accounts:prospect_player_add"),
            {"first_name": "kim", "last_name": "lee", "date_of_birth": "2014-02-02", "positions": ["RP"]},
        )
        kid = self.user.prospective_players.get()
        self.assertEqual(kid.first_name, "Kim")
        self.assertContains(self.client.get(reverse("accounts:prospect_player_edit", args=[kid.pk])), "Remove Player")
        self.client.post(
            reverse("accounts:prospect_player_edit", args=[kid.pk]),
            {"first_name": "Kim", "last_name": "Lee", "date_of_birth": "2014-02-02", "positions": ["C"]},
        )
        self.assertEqual([p.position for p in kid.positions.all()], ["C"])
        self.client.post(reverse("accounts:prospect_player_delete", args=[kid.pk]))
        self.assertFalse(self.user.prospective_players.exists())

    def test_promotion_marks_kid_joined(self):
        from apps.tryouts.models import ProspectivePlayer, TryoutSignup
        from apps.tryouts.roster import promote_signup_to_roster

        self.client.force_login(self.user)
        self.client.post(reverse("tryouts:signup"), self.signup_data(save_player="on"))
        signup = TryoutSignup.objects.get()
        signup.responded_by = self.user
        player = promote_signup_to_roster(signup, created_by=self.user)
        kid = ProspectivePlayer.objects.get()
        self.assertEqual(kid.promoted_player, player)
        response = self.client.get(reverse("accounts:dashboard_prospect"))
        self.assertEqual(len(response.context["kids"]), 0)

    def test_respond_asks_account_holders_to_log_in(self):
        from apps.tryouts.models import TryoutDecision, TryoutResponseInvite, TryoutSignup

        self.client.force_login(self.user)
        self.client.post(reverse("tryouts:signup"), self.signup_data())
        signup = TryoutSignup.objects.get()
        signup.coach_decision = TryoutDecision.INVITE
        signup.save()
        invite = TryoutResponseInvite.objects.create(signup=signup)
        self.client.logout()
        response = self.client.get(reverse("tryouts:respond", args=[invite.token]))
        self.assertContains(response, "You signed up with an account")
        self.assertNotContains(response, "Create Account")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class InterestedFamiliesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import UserRole

        admin_role = UserRole.objects.create(role=Role.ADMIN)
        cls.admin = User.objects.create_user(email="admin@example.com", password="x")
        cls.admin.roles.add(admin_role)
        cls.opted = User.objects.create_user(email="in@example.com", password="x", first_name="In")
        cls.opted.info_emails_opt_in = True
        cls.opted.save()
        cls.unverified = User.objects.create_user(email="unv@example.com", password="x")
        cls.unverified.info_emails_opt_in = True
        cls.unverified.email_verified = False
        cls.unverified.save()
        User.objects.create_user(email="never@example.com", password="x")

    def send(self, **extra):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("accounts:tryout_mass_email"),
            {"audience": "interested", "subject": "Tryouts", "body": "Hello!", "recipient": ["in@example.com", "never@example.com"], **extra},
        )

    def test_only_opted_in_verified_users_are_listed(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:tryout_mass_email"), {"audience": "interested"})
        self.assertEqual([r["email"] for r in response.context["all_recipients"]], ["in@example.com"])

    def test_coach_cannot_use_interested_audience(self):
        coach = User.objects.create_user(email="c@example.com", password="x")
        from .models import UserRole

        coach.roles.add(UserRole.objects.create(role=Role.COACH))
        self.client.force_login(coach)
        response = self.client.get(reverse("accounts:tryout_mass_email"), {"audience": "interested"})
        self.assertEqual(response.status_code, 403)

    def test_send_gives_each_person_their_own_unsubscribe_link(self):
        from apps.tryouts.models import TryoutMassEmail

        response = self.send()
        self.assertEqual(response.status_code, 302)
        # "never@" wasn't in the computed list, so a forged address is ignored.
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["in@example.com"])
        self.assertIn("/accounts/unsubscribe/", message.body)
        self.assertIn("/accounts/unsubscribe/", message.extra_headers["List-Unsubscribe"])
        self.assertEqual(TryoutMassEmail.objects.get().audience, "interested")

    def test_unsubscribe_needs_a_post_and_no_login(self):
        from .emails import make_unsubscribe_token

        url = reverse("accounts:unsubscribe", args=[make_unsubscribe_token(self.opted)])
        self.assertContains(self.client.get(url), "Unsubscribe me")
        self.opted.refresh_from_db()
        self.assertTrue(self.opted.info_emails_opt_in)  # a GET (e.g. a link scanner) changes nothing
        self.assertContains(self.client.post(url), "You're unsubscribed")
        self.opted.refresh_from_db()
        self.assertFalse(self.opted.info_emails_opt_in)
        self.assertIsNotNone(self.opted.info_emails_opted_out_at)

    def test_one_click_post_from_mail_app(self):
        from django.test import Client

        from .emails import make_unsubscribe_token

        url = reverse("accounts:unsubscribe", args=[make_unsubscribe_token(self.opted)])
        response = Client(enforce_csrf_checks=True).post(url, {"List-Unsubscribe": "One-Click"})
        self.assertEqual(response.status_code, 200)
        self.opted.refresh_from_db()
        self.assertFalse(self.opted.info_emails_opt_in)

    def test_bad_token(self):
        response = self.client.post(reverse("accounts:unsubscribe", args=["junk"]))
        self.assertContains(response, "didn't work")

    def test_toggle_from_my_account(self):
        self.client.force_login(self.opted)
        self.client.post(reverse("accounts:info_emails_set"), {"opt_in": "no"})
        self.opted.refresh_from_db()
        self.assertFalse(self.opted.info_emails_opt_in)
        self.client.post(reverse("accounts:info_emails_set"), {"opt_in": "yes"})
        self.opted.refresh_from_db()
        self.assertTrue(self.opted.info_emails_opt_in)
        self.assertIsNone(self.opted.info_emails_opted_out_at)

    def test_resend_batch_payload(self):
        from apps.tryouts.emails import send_personalized_mass_email

        with override_settings(EMAIL_BACKEND="anymail.backends.resend.EmailBackend", ANYMAIL={"RESEND_API_KEY": "k"}):
            with mock.patch("apps.tryouts.emails.requests.post") as post:
                sent = send_personalized_mass_email(
                    "Hi", [("a@x.com", "body A", {"List-Unsubscribe": "<u1>"}), ("b@x.com", "body B", {})], ["r@x.com"]
                )
        self.assertEqual(sent, ["a@x.com", "b@x.com"])
        payload = post.call_args.kwargs["json"]
        self.assertEqual([m["text"] for m in payload], ["body A", "body B"])
        self.assertEqual(payload[0]["headers"], {"List-Unsubscribe": "<u1>"})
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer k")
