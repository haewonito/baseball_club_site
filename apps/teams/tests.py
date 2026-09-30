from django.test import SimpleTestCase

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
