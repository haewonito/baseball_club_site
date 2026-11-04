"""Permission and scoping tests for the dashboard views: who may touch which team's
roster, try-out sign-ups and fees, plus try-out promotion."""
import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.fees.models import Fee
from apps.teams.models import Team, TeamCoach
from apps.tryouts.models import TryoutDecision, TryoutDecisionChange, TryoutSignup
from apps.tryouts.roster import find_existing_player, promote_signup_to_roster

from .models import ParentPlayerLink, Player, Role, User, UserRole

PLAIN_STORAGE = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


def make_user(email, *roles):
    user = User.objects.create_user(email, "pw")
    for role in roles:
        user.roles.add(UserRole.objects.get_or_create(role=role)[0])
    return user


def make_player(team, first="Sam", last="Kid"):
    return Player.objects.create(
        first_name=first, last_name=last, date_of_birth=datetime.date(2016, 1, 1), team=team
    )


def make_signup(team, **extra):
    data = dict(
        team=team,
        player_first_name="Ann",
        player_last_name="Kid",
        date_of_birth=datetime.date(2016, 5, 5),
        parent_first_name="Pat",
        parent_last_name="Kid",
        parent_phone="555-0100",
        parent_email="pat@example.com",
    )
    data.update(extra)
    return TryoutSignup.objects.create(**data)


@PLAIN_STORAGE
class ScopingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team_a = Team.objects.create(name="10U A", division="10U", season_year=2030)
        cls.team_b = Team.objects.create(name="10U B", division="10U", season_year=2030)
        cls.coach = make_user("coach@example.com", Role.COACH)
        TeamCoach.objects.create(team=cls.team_a, coach=cls.coach)
        cls.admin = make_user("admin@example.com", Role.ADMIN)
        cls.parent = make_user("parent@example.com", Role.PARENT)
        cls.player_a = make_player(cls.team_a, "Al")
        cls.player_b = make_player(cls.team_b, "Bo")


class RosterScopingTests(ScopingTestCase):
    def roster(self, team):
        return self.client.get(reverse("accounts:coach_roster", args=[team.pk]))

    def test_coach_sees_own_team_roster_only(self):
        self.client.force_login(self.coach)
        self.assertEqual(self.roster(self.team_a).status_code, 200)
        self.assertEqual(self.roster(self.team_b).status_code, 404)

    def test_admin_sees_any_roster(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.roster(self.team_b).status_code, 200)

    def test_parent_cannot_open_roster(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.roster(self.team_a).status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        response = self.roster(self.team_a)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_bulk_move_only_moves_players_from_own_team(self):
        self.client.force_login(self.coach)
        url = reverse("accounts:coach_roster_bulk_move", args=[self.team_a.pk])
        self.client.post(
            url,
            {"player_ids": [self.player_a.pk, self.player_b.pk], "destination_team": self.team_b.pk},
        )
        self.player_a.refresh_from_db()
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_a.team, self.team_b)
        self.assertEqual(self.player_b.team, self.team_b)  # was never on A, so untouched

    def test_coach_cannot_bulk_move_from_other_team(self):
        self.client.force_login(self.coach)
        url = reverse("accounts:coach_roster_bulk_move", args=[self.team_b.pk])
        response = self.client.post(url, {"player_ids": [self.player_b.pk], "destination_team": self.team_a.pk})
        self.assertEqual(response.status_code, 404)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.team, self.team_b)

    def test_coach_events_page_is_scoped(self):
        self.client.force_login(self.coach)
        own = reverse("accounts:coach_events", args=[self.team_a.pk, "practices"])
        other = reverse("accounts:coach_events", args=[self.team_b.pk, "practices"])
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 404)


class TryoutDecisionTests(ScopingTestCase):
    def decide(self, signup, decision="invite"):
        return self.client.post(
            reverse("accounts:coach_tryout_decision_change", args=[signup.pk]),
            {"coach_decision": decision},
        )

    def test_coach_can_decide_own_teams_signup_and_it_is_audited(self):
        signup = make_signup(self.team_a)
        self.client.force_login(self.coach)
        self.assertEqual(self.decide(signup).status_code, 200)
        signup.refresh_from_db()
        self.assertEqual(signup.coach_decision, TryoutDecision.INVITE)
        change = TryoutDecisionChange.objects.get()
        self.assertEqual((change.changed_by, change.new_decision), (self.coach, "invite"))

    def test_coach_cannot_decide_other_teams_signup(self):
        signup = make_signup(self.team_b)
        self.client.force_login(self.coach)
        self.assertEqual(self.decide(signup).status_code, 403)
        signup.refresh_from_db()
        self.assertEqual(signup.coach_decision, TryoutDecision.UNDECIDED)
        self.assertFalse(TryoutDecisionChange.objects.exists())

    def test_admin_can_decide_any_signup(self):
        signup = make_signup(self.team_b)
        self.client.force_login(self.admin)
        self.assertEqual(self.decide(signup, "not_selected").status_code, 200)

    def test_parent_cannot_decide(self):
        signup = make_signup(self.team_a)
        self.client.force_login(self.parent)
        self.assertEqual(self.decide(signup).status_code, 403)

    def test_invalid_decision_is_rejected_and_unchanged_decision_not_audited(self):
        signup = make_signup(self.team_a)
        self.client.force_login(self.coach)
        self.assertEqual(self.decide(signup, "bogus").status_code, 400)
        self.decide(signup, TryoutDecision.UNDECIDED)
        self.assertFalse(TryoutDecisionChange.objects.exists())

    def test_changing_decision_clears_sent_email_stamp(self):
        from django.utils import timezone

        signup = make_signup(self.team_a, coach_decision="invite", decision_emailed_at=timezone.now())
        self.client.force_login(self.coach)
        self.decide(signup, "not_selected")
        signup.refresh_from_db()
        self.assertIsNone(signup.decision_emailed_at)


class AdminOnlyPageTests(ScopingTestCase):
    def test_admin_pages_refuse_coaches_and_parents(self):
        urls = [
            reverse("accounts:admin_fees_list"),
            reverse("accounts:admin_fee_add"),
            reverse("accounts:admin_fee_player", args=[self.player_a.pk]),
            reverse("accounts:admin_invoices_list"),
            reverse("accounts:admin_tryouts_list"),
            reverse("accounts:admin_tryout_posters_list"),
        ]
        for user in (self.coach, self.parent):
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, (user.email, url))

    def test_record_payment_requires_admin(self):
        fee = Fee.objects.create(player=self.player_a, description="Dues", amount_due=50)
        self.client.force_login(self.coach)
        response = self.client.post(
            reverse("accounts:admin_fee_record_payment", args=[self.player_a.pk]),
            {"amount": "10", "method": "cash", "paid_at": "2030-01-01"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(fee.payments.count(), 0)


class FeeFanOutTests(ScopingTestCase):
    def test_one_full_amount_fee_per_checked_player(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_fee_add"),
            {
                "description": "Uniform",
                "amount_due": "80.00",
                "players": [self.player_a.pk, self.player_b.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        fees = Fee.objects.filter(description="Uniform")
        self.assertEqual(fees.count(), 2)
        self.assertEqual({f.amount_due for f in fees}, {80})
        self.assertEqual({f.player_id for f in fees}, {self.player_a.pk, self.player_b.pk})
        self.assertTrue(all(f.team_id is None for f in fees))

    def test_single_player_goes_to_their_fee_page(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_fee_add"),
            {"description": "Fee", "amount_due": "5", "players": [self.player_a.pk]},
        )
        self.assertRedirects(
            response, reverse("accounts:admin_fee_player", args=[self.player_a.pk]), fetch_redirect_response=False
        )

    def test_no_players_selected_creates_nothing(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:admin_fee_add"), {"description": "Fee", "amount_due": "5"})
        self.assertFalse(Fee.objects.exists())


class PromoteSignupTests(ScopingTestCase):
    def test_promote_creates_player_and_parent_link(self):
        signup = make_signup(self.team_a, responded_by=self.parent)
        player = promote_signup_to_roster(signup, created_by=self.admin)
        self.assertEqual((player.team, player.first_name), (self.team_a, "Ann"))
        signup.refresh_from_db()
        self.assertEqual(signup.promoted_player, player)
        self.assertTrue(ParentPlayerLink.objects.filter(parent=self.parent, player=player).exists())

    def test_promoting_twice_returns_none(self):
        signup = make_signup(self.team_a, responded_by=self.parent)
        promote_signup_to_roster(signup, created_by=self.admin)
        self.assertIsNone(promote_signup_to_roster(signup, created_by=self.admin))
        self.assertEqual(Player.objects.filter(first_name="Ann").count(), 1)

    def test_no_date_of_birth_is_not_promoted(self):
        signup = make_signup(self.team_a, date_of_birth=None)
        self.assertIsNone(promote_signup_to_roster(signup, created_by=self.admin))

    def test_returning_player_is_moved_not_duplicated(self):
        kid = make_player(self.team_b, "Ann", "Kid")
        kid.date_of_birth = datetime.date(2016, 5, 5)
        kid.save()
        ParentPlayerLink.objects.create(parent=self.parent, player=kid)
        signup = make_signup(self.team_a, responded_by=self.parent)
        found = find_existing_player(signup, self.parent)
        self.assertEqual(found, kid)
        promote_signup_to_roster(signup, created_by=self.admin, existing_player=found)
        kid.refresh_from_db()
        self.assertEqual(kid.team, self.team_a)
        self.assertEqual(Player.objects.filter(first_name="Ann").count(), 1)

    def test_find_existing_player_ignores_removed_links_and_other_parents(self):
        kid = make_player(self.team_b, "Ann", "Kid")
        kid.date_of_birth = datetime.date(2016, 5, 5)
        kid.save()
        signup = make_signup(self.team_a)
        self.assertIsNone(find_existing_player(signup, self.parent))  # not linked
        self.assertIsNone(find_existing_player(signup, None))


@PLAIN_STORAGE
class HomeBannerTests(ScopingTestCase):
    def test_posters_come_first_and_link_to_signup_pictures_link_to_team(self):
        from apps.content.models import HeroImage
        from apps.tryouts.models import TryoutPoster

        HeroImage.objects.create(image="hero/a.jpg", team=self.team_a)
        TryoutPoster.objects.create(title="P1", image="p1.jpg", poster_type="initial", display_order=2)
        TryoutPoster.objects.create(title="P2", image="p2.jpg", poster_type="initial", display_order=1)
        TryoutPoster.objects.create(title="Off", image="p3.jpg", poster_type="initial", is_active=False)
        slides = self.client.get(reverse("home")).context["banner_slides"]
        self.assertEqual(
            [(s["kind"], s["poster"].title if s["kind"] == "poster" else None) for s in slides],
            [("poster", "P2"), ("poster", "P1"), ("picture", None)],
        )
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(reverse("tryouts:signup"), html)
        self.assertIn(reverse("teams:detail", args=[self.team_a.pk]), html)

    def test_several_posters_can_be_active_together(self):
        from apps.tryouts.models import TryoutPoster

        for n in range(2):
            poster = TryoutPoster(title=f"P{n}", image="p.jpg", poster_type="initial", is_active=True)
            poster.full_clean(exclude=["image", "uploaded_by"])
            poster.save()
        self.assertEqual(TryoutPoster.objects.filter(is_active=True).count(), 2)


@PLAIN_STORAGE
class FamilySignupChangeTests(ScopingTestCase):
    def setUp(self):
        self.client.force_login(self.parent)
        self.signup = make_signup(self.team_a, user=self.parent, parent_email=self.parent.email)

    def edit_data(self, **extra):
        data = {
            "team": self.team_a.pk,
            "player_first_name": "Annie",
            "player_last_name": "Kid",
            "date_of_birth": "2016-05-05",
            "positions": ["SS"],
            "parent_first_name": "Pat",
            "parent_last_name": "Kid",
            "parent_phone": "555-0100",
            "parent_email": self.parent.email,
        }
        data.update(extra)
        return data

    def edit(self, **extra):
        return self.client.post(reverse("accounts:prospect_signup_edit", args=[self.signup.pk]), self.edit_data(**extra))

    def withdraw(self):
        return self.client.post(reverse("accounts:prospect_signup_withdraw", args=[self.signup.pk]))

    def test_edit_updates_the_signup_and_positions(self):
        self.edit()
        self.signup.refresh_from_db()
        self.assertEqual(self.signup.player_first_name, "Annie")
        self.assertEqual(self.signup.positions_display, "Shortstop")
        self.assertIsNotNone(self.signup.family_edited_at)

    def test_changing_team_moves_it_to_the_new_teams_list_and_resets_the_decision(self):
        self.team_b.accepting_tryouts = True
        self.team_b.save()
        self.signup.coach_decision = TryoutDecision.INVITE
        self.signup.save()
        self.edit(team=self.team_b.pk)
        self.signup.refresh_from_db()
        self.assertEqual((self.signup.team, self.signup.coach_decision), (self.team_b, TryoutDecision.UNDECIDED))
        self.assertTrue(TryoutDecisionChange.objects.filter(signup=self.signup, changed_by=self.parent).exists())

    def test_locked_once_decision_email_sent(self):
        from django.utils import timezone

        self.signup.decision_emailed_at = timezone.now()
        self.signup.save()
        self.edit()
        self.assertEqual(self.withdraw().status_code, 302)
        self.signup.refresh_from_db()
        self.assertEqual(self.signup.player_first_name, "Ann")
        self.assertIsNone(self.signup.withdrawn_at)

    def test_other_familys_signup_is_not_reachable(self):
        other = make_user("other@example.com", Role.PARENT)
        self.client.force_login(other)
        self.assertEqual(self.withdraw().status_code, 404)

    def test_withdraw_before_the_tryout_deletes_the_row(self):
        self.withdraw()
        self.assertFalse(TryoutSignup.objects.filter(pk=self.signup.pk).exists())

    def test_withdraw_after_a_decision_keeps_the_row_crossed_out_at_the_end(self):
        self.signup.coach_decision = TryoutDecision.NOT_SELECTED
        self.signup.save()
        self.withdraw()
        self.signup.refresh_from_db()
        self.assertIsNotNone(self.signup.withdrawn_at)
        make_signup(self.team_a, player_first_name="Zed", player_last_name="Zulu")
        make_signup(self.team_a, player_first_name="Abe", player_last_name="Aaa")
        self.client.force_login(self.coach)
        shown = list(self.client.get(reverse("accounts:coach_tryouts")).context["signups"])
        self.assertEqual([s.player_last_name for s in shown], ["Aaa", "Zulu", "Kid"])
        self.assertTrue(shown[-1].is_withdrawn)

    def test_withdrawn_signups_cannot_be_decided_or_emailed(self):
        from django.utils import timezone

        self.signup.withdrawn_at = timezone.now()
        self.signup.save()
        self.client.force_login(self.coach)
        decide = self.client.post(
            reverse("accounts:coach_tryout_decision_change", args=[self.signup.pk]), {"coach_decision": "invite"}
        )
        self.assertEqual(decide.status_code, 400)
        recipients = self.client.get(reverse("accounts:tryout_mass_email") + "?audience=tryouts").context["recipients"]
        self.assertEqual(recipients, [])
