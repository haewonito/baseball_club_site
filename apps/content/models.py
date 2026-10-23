from django.core.validators import MaxValueValidator
from django.db import models


class HeroImage(models.Model):
    """One picture in the banner slideshow right below the site header (home page). Managed in Django admin."""

    image = models.ImageField(upload_to="hero/")
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
