from django.test import TestCase, override_settings
from django.urls import reverse

from .models import HeroImage


# The test run has no collectstatic manifest, so pages that use {% static %} need plain storage.
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class SiteContentTests(TestCase):
    def test_about_page_has_the_mission_blurb_and_home_does_not(self):
        self.assertContains(self.client.get(reverse("about")), "competitive baseball")
        self.assertNotContains(self.client.get(reverse("home")), "competitive baseball")

    def test_nav_links_to_about(self):
        self.assertContains(self.client.get(reverse("home")), reverse("about"))

    def test_home_banner_shows_only_active_pictures_in_order(self):
        HeroImage.objects.create(image="hero/b.jpg", alt_text="second", sort_order=2)
        HeroImage.objects.create(image="hero/a.jpg", alt_text="first", sort_order=1)
        HeroImage.objects.create(image="hero/c.jpg", alt_text="inactive-pic", is_active=False)
        response = self.client.get(reverse("home"))
        html = response.content.decode()
        self.assertLess(html.index("first"), html.index("second"))
        self.assertNotIn("inactive-pic", html)
        self.assertContains(response, "Show picture", count=2)

    def test_home_without_pictures_still_has_a_heading(self):
        self.assertContains(self.client.get(reverse("home")), "<h1>Choice Select</h1>")
