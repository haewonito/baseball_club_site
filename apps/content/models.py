from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class HeroImage(models.Model):
    """One picture in the banner slideshow right below the site header (home page). Managed in Django admin."""

    image = models.ImageField(upload_to="hero/")
    # Where clicking the picture goes: this team's detail page. Required in the
    # admin form; nullable in the database so existing rows could be migrated
    # and so deleting a team just leaves its pictures unlinked.
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        related_name="hero_images",
        limit_choices_to={"is_public": True, "is_deleted_placeholder": False},
        help_text="Clicking this picture on the home page opens this team's page.",
    )
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="Describes the picture for screen readers, e.g. \"Players warming up before a game\".",
    )
    # Where the banner's crop window sits on the picture, 0-100 on each axis
    # (CSS object-position percentages). Set by dragging in Django admin
    # (static/js/hero-crop.js); 50/50 is centered.
    focus_x = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
    focus_y = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
    # Percent: 100 shows the whole picture (as far as the banner shape allows),
    # higher zooms in evenly, which is how a side is "cut". Never stretches.
    zoom = models.PositiveSmallIntegerField(
        default=100, validators=[MinValueValidator(100), MaxValueValidator(300)]
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0, help_text="Lower numbers show first."
    )
    is_active = models.BooleanField(
        default=True, help_text="Untick to hide a picture without deleting it."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Banner Picture"
        verbose_name_plural = "Banner Pictures"

    def __str__(self):
        return self.alt_text or f"Banner picture {self.pk}"
