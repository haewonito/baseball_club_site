from django.test import SimpleTestCase, TestCase, override_settings

from apps.teams.models import Team


class TeamDisplayNameTests(SimpleTestCase):
    def test_display_name_omits_the_redundant_club_prefix(self):
        team = Team(name="Choice Select 10U")

        self.assertEqual(team.display_name, "10U")

    def test_display_name_preserves_names_without_the_club_prefix(self):
        team = Team(name="10U Bulldogs")

        self.assertEqual(team.display_name, "10U Bulldogs")

    def test_string_representation_is_unchanged(self):
        team = Team(name="Choice Select 10U", season_year=2027)

        self.assertEqual(str(team), "Choice Select 10U (2026-2027)")


import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import Role, User, UserRole
from apps.teams.models import TeamCoach, TeamPhoto

_TEST_MEDIA = tempfile.mkdtemp()


def _png(name="a.png"):
    buffer = BytesIO()
    Image.new("RGB", (20, 10), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


# No collectstatic manifest in tests, and uploads go to a throwaway folder.
@override_settings(
    MEDIA_ROOT=_TEST_MEDIA,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class TeamPhotoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        self.team = Team.objects.create(name="Choice Select 10U", division="10U", season_year=2027)
        self.other = Team.objects.create(name="Choice Select 12U", division="12U", season_year=2027)
        coach_role, _ = UserRole.objects.get_or_create(role=Role.COACH)
        self.coach = User.objects.create_user("coach@example.com", "pw-12345-x")
        self.coach.roles.add(coach_role)
        TeamCoach.objects.create(coach=self.coach, team=self.team)
        self.stranger = User.objects.create_user("x@example.com", "pw-12345-x")

    def _photo(self, team=None, **kw):
        return TeamPhoto.objects.create(team=team or self.team, image=_png(), **kw)

    def test_featuring_a_photo_unfeatures_the_previous_one(self):
        first = self._photo(is_featured=True)
        second = self._photo()
        self.client.force_login(self.coach)
        self.client.post(reverse("teams:photo_feature", args=[self.team.pk, second.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_featured)
        self.assertTrue(second.is_featured)

    def test_posting_feature_on_the_featured_photo_clears_it(self):
        photo = self._photo(is_featured=True)
        self.client.force_login(self.coach)
        self.client.post(reverse("teams:photo_feature", args=[self.team.pk, photo.pk]))
        photo.refresh_from_db()
        self.assertFalse(photo.is_featured)

    def test_coach_can_upload_several(self):
        self.client.force_login(self.coach)
        self.client.post(
            reverse("teams:photo_add", args=[self.team.pk]), {"images": [_png("a.png"), _png("b.png")]}
        )
        self.assertEqual(self.team.photos.count(), 2)
        self.assertEqual(self.team.photos.first().uploaded_by, self.coach)

    def test_other_users_and_other_teams_coaches_are_refused(self):
        photo = self._photo()
        for url in (
            reverse("teams:photo_add", args=[self.team.pk]),
            reverse("teams:photo_feature", args=[self.team.pk, photo.pk]),
            reverse("teams:photo_delete", args=[self.team.pk, photo.pk]),
        ):
            self.client.force_login(self.stranger)
            self.assertEqual(self.client.post(url).status_code, 403)
        # The coach of one team can't touch another team's photos.
        other_photo = self._photo(team=self.other)
        self.client.force_login(self.coach)
        response = self.client.post(reverse("teams:photo_delete", args=[self.other.pk, other_photo.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(TeamPhoto.objects.filter(pk=other_photo.pk).exists())

    def test_teams_page_banner_shows_only_featured_photos_of_public_teams(self):
        self._photo(is_featured=True)
        self._photo(team=self.other)  # not featured
        response = self.client.get(reverse("teams:index"))
        self.assertEqual([t.pk for t in response.context["banner_teams"]], [self.team.pk])
        self.assertContains(response, reverse("teams:detail", args=[self.team.pk]))

    def test_photo_gallery_is_only_on_the_page_for_managers(self):
        self._photo()
        url = reverse("teams:detail", args=[self.team.pk])
        self.assertNotContains(self.client.get(url), "Team Photos")
        self.client.force_login(self.coach)
        self.assertContains(self.client.get(url), "Team Photos")

    def test_header_dropdown_lists_public_teams(self):
        Team.objects.filter(pk=self.other.pk).update(is_public=False)
        response = self.client.get(reverse("teams:index"))
        self.assertContains(response, "site-nav__submenu")
        self.assertContains(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertNotContains(response, reverse("teams:detail", args=[self.other.pk]))


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class TeamAdminDefaultsTests(TestCase):
    def test_add_form_season_year_defaults_to_the_season_ending_year(self):
        from django.utils import timezone

        from apps.accounts.models import User

        today = timezone.localdate()

        self.client.force_login(User.objects.create_superuser("root@example.com", "pw"))
        response = self.client.get("/admin/teams/team/add/")
        self.assertEqual(response.context["adminform"].form["season_year"].value(), today.year + 1 if today.month >= 8 else today.year)
        self.assertContains(response, "Season Ending Year")

    def test_team_photo_help_text_is_visible_not_a_tooltip(self):
        from apps.accounts.models import User
        from apps.teams.models import Team

        self.client.force_login(User.objects.create_superuser("root2@example.com", "pw"))
        team = Team.objects.create(name="T", division="10U", season_year=2030)
        response = self.client.get(f"/admin/teams/team/{team.pk}/change/")
        self.assertContains(response, "Shown in the Teams page banner. Only one picture per team can be")
        self.assertContains(response, 'class="help"')
