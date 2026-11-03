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
        self.assertContains(response, "Next picture")
        self.assertContains(response, "Previous picture")

    def test_picture_focus_is_applied(self):
        HeroImage.objects.create(image="hero/a.jpg", alt_text="x", focus_x=30, focus_y=0, zoom=150)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "object-position: 30% 0%")
        self.assertContains(response, "scale(calc(150 / 100))")

    def test_single_picture_has_no_chevrons(self):
        HeroImage.objects.create(image="hero/a.jpg", alt_text="only")
        self.assertNotContains(self.client.get(reverse("home")), "Next picture")

    def test_home_without_pictures_still_has_a_heading(self):
        self.assertContains(self.client.get(reverse("home")), "<h1>Choice Select</h1>")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class HeroImageAdminTests(TestCase):
    def setUp(self):
        from apps.accounts.models import User

        self.client.force_login(User.objects.create_superuser(email="su@example.com", password="x"))

    def test_add_and_change_forms_show_the_drag_frame(self):
        response = self.client.get("/admin/content/heroimage/add/")
        self.assertContains(response, "data-crop-frame")
        self.assertContains(response, "js/hero-crop.js")
        image = HeroImage.objects.create(image="hero/a.jpg", focus_x=20, focus_y=80)
        response = self.client.get(f"/admin/content/heroimage/{image.pk}/change/")
        self.assertContains(response, "object-position:20% 80%")
        self.assertContains(response, 'name="focus_x"')


from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BugReport


@override_settings(
    BUG_REPORT_DAILY_LIMIT=2,
    BUG_REPORT_EMAIL="manager@example.com",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class BugReportTests(TestCase):
    def send(self, message="The schedule page is blank", **extra):
        return self.client.post(
            reverse("report_bug"), {"message": message, "page": "/schedule/", **extra}
        )

    def test_report_is_emailed_to_manager_with_reply_to(self):
        response = self.send(reporter_email="fan@example.com")
        self.assertRedirects(response, reverse("report_bug") + "?sent=1", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["manager@example.com"])
        self.assertEqual(message.reply_to, ["fan@example.com"])
        self.assertIn("The schedule page is blank", message.body)
        self.assertIn("/schedule/", message.body)

    def test_daily_limit_blocks_further_reports(self):
        self.send()
        self.send()
        self.assertEqual(len(mail.outbox), 2)
        self.send("third")
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(BugReport.objects.count(), 2)
        page = self.client.get(reverse("report_bug"))
        self.assertContains(page, "reached today")
        self.assertNotContains(page, "Send Report")

    def test_failed_send_does_not_use_up_the_limit(self):
        from unittest import mock

        with mock.patch("django.core.mail.EmailMessage.send", side_effect=OSError("down")):
            response = self.send()
        self.assertContains(response, "couldn't be sent")
        self.assertEqual(BugReport.objects.count(), 0)

    def test_honeypot_and_empty_message_send_nothing(self):
        self.send(website="http://spam.example")
        self.client.post(reverse("report_bug"), {"message": ""})
        self.assertEqual(len(mail.outbox), 0)

    def test_footer_links_to_form(self):
        self.assertContains(self.client.get(reverse("home")), reverse("report_bug"))
