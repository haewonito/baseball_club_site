from io import BytesIO
from pathlib import Path

from django import forms
from django.core.files.base import ContentFile
from PIL import Image, ImageOps
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.fees.models import Fee, Payment
from apps.schedule.models import Event
from apps.teams.models import CoachProfile, PlayerPosition, Position, Team
from apps.tryouts.models import TryoutPoster

from .models import User

from .models import Player, PlayerGalleryPhoto


class PlayerRosterForm(forms.ModelForm):
    """
    Used for both adding a new player to a team and editing an existing
    one -- `team` isn't a form field, it's set on the instance by the view
    before binding, the same way TryoutSignupForm handles `positions`
    (see apps/tryouts/forms.py) via a separate M2M-style save step.
    """

    positions = forms.MultipleChoiceField(
        choices=Position.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Position(s)",
    )

    class Meta:
        model = Player
        fields = ["first_name", "last_name", "date_of_birth", "jersey_number"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["positions"].initial = list(
                self.instance.positions.values_list("position", flat=True)
            )

    def save(self, commit=True):
        player = super().save(commit=commit)
        if commit:
            self._save_positions(player)
        return player

    def _save_positions(self, player):
        player.positions.all().delete()
        PlayerPosition.objects.bulk_create(
            PlayerPosition(player=player, position=code)
            for code in self.cleaned_data.get("positions", [])
        )


class EventForm(forms.ModelForm):
    """Practices and tournaments both. `team` and `event_type` aren't form
    fields -- set on the instance by the view before binding, so a coach
    can't reassign an event to a different team or relabel a practice as a
    tournament (or vice versa) through this form."""

    # HTML5 datetime-local inputs submit "YYYY-MM-DDTHH:MM" (T-separated),
    # which isn't in Django's default DATETIME_INPUT_FORMATS (space-
    # separated) -- declared explicitly here so parsing the POST works,
    # not just rendering the initial value.
    start_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    end_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        required=False,
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "start_datetime",
            "end_datetime",
            "location_name",
            "location_address",
            "notes",
            "status",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class FeeForm(forms.ModelForm):
    """
    Exactly one of `player`/`team` must be set -- a Fee is either for one
    player or team-wide (see the Fee docstring in apps/fees/models.py).
    The model itself doesn't enforce this with a DB constraint. On
    admin_fee_add, choosing `team` doesn't save a team-wide row at all --
    it fans out into one full-amount Fee per current player on that team
    (see the view); `team` stays a real, saveable field here mainly so
    admin_fee_edit can keep editing whatever a Fee instance already has.
    """

    class Meta:
        model = Fee
        fields = ["player", "team", "description", "amount_due", "due_date"]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["player"].queryset = Player.objects.order_by("last_name", "first_name")
        self.fields["team"].queryset = Team.objects.filter(is_deleted_placeholder=False).order_by(
            "-season_year", "division"
        )

    def clean(self):
        cleaned_data = super().clean()
        player = cleaned_data.get("player")
        team = cleaned_data.get("team")
        if bool(player) == bool(team):
            raise forms.ValidationError(
                "Choose exactly one of Player or Team -- not both, not neither."
            )
        if team and not team.players.exists():
            raise forms.ValidationError(f'"{team}" has no players -- nothing to charge.')
        return cleaned_data


class PaymentForm(forms.ModelForm):
    """`fee` and `recorded_by` aren't form fields -- set on the instance by
    the view, the same pattern as EventForm's team/event_type."""

    class Meta:
        model = Payment
        fields = ["amount", "method", "paid_at", "notes"]
        widgets = {
            "paid_at": forms.DateInput(attrs={"type": "date"}),
        }


class CoachProfileForm(forms.ModelForm):
    """`coach` isn't a form field -- the profile is looked up/created from
    the URL's user id, the same pattern used throughout this file."""

    class Meta:
        model = CoachProfile
        fields = ["bio_text", "photo", "contact_email"]
        widgets = {
            "bio_text": forms.Textarea(attrs={"rows": 6}),
        }


class PlayerProfileForm(forms.ModelForm):
    """
    The parent's own editable subset of Player -- name/DOB/jersey/position
    stay coach-or-admin-only via PlayerRosterForm; this is only ever used
    from parent_player_profile_edit (parent, or admin as an override).
    """

    class Meta:
        model = Player
        fields = ["photo", "description", "is_public_profile"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }


class _MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class _MultipleImageField(forms.ImageField):
    """Django's documented pattern for a multi-file upload field -- cleans
    each selected file as its own image and returns a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", _MultipleImageInput(attrs={"accept": "image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(d, initial) for d in data]
        return [single_clean(data, initial)]


GALLERY_MAX_PHOTOS = 30
GALLERY_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
GALLERY_MAX_DIMENSION = 1600


def downsize_image(uploaded):
    """
    Re-encodes an upload as a JPEG no larger than GALLERY_MAX_DIMENSION on
    its long side -- phone photos are often several MB, which adds up
    against R2's free tier. exif_transpose first, so phone photos taken
    sideways don't end up rotated once the EXIF orientation is dropped.
    """
    uploaded.seek(0)
    image = ImageOps.exif_transpose(Image.open(uploaded)).convert("RGB")
    image.thumbnail((GALLERY_MAX_DIMENSION, GALLERY_MAX_DIMENSION))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=82, optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{Path(uploaded.name).stem}.jpg")


class PlayerGalleryPhotoForm(forms.Form):
    images = _MultipleImageField(label="Add photos")

    def __init__(self, *args, player, **kwargs):
        self.player = player
        super().__init__(*args, **kwargs)

    def clean_images(self):
        images = self.cleaned_data["images"]
        for image in images:
            if image.size > GALLERY_MAX_UPLOAD_BYTES:
                raise forms.ValidationError(f"\"{image.name}\" is too large (20 MB max per photo).")
        remaining = GALLERY_MAX_PHOTOS - self.player.gallery_photos.count()
        if len(images) > remaining:
            raise forms.ValidationError(
                f"The gallery holds up to {GALLERY_MAX_PHOTOS} photos -- "
                f"there's room for {max(remaining, 0)} more. Delete some first to add more."
            )
        return images


class TryoutPosterForm(forms.ModelForm):
    class Meta:
        model = TryoutPoster
        fields = ["poster_type", "title", "image", "is_active", "display_order"]


class InviteClaimSignupForm(forms.Form):
    """
    Account creation for someone claiming a ParentInvite who doesn't
    already have a login. Plain forms.Form (not a User ModelForm) since it
    needs the password1/password2 pair and doesn't touch roles/is_active
    directly -- those are set by the view after save().
    """

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_email(self):
        # Case-insensitive: "James@x.com" must collide with an existing
        # "james@x.com" the same way User's DB constraint requires.
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists -- log in instead."
            )
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords don't match.")
        elif password1:
            try:
                validate_password(password1)
            except DjangoValidationError as exc:
                self.add_error("password1", exc)
        return cleaned_data

    def save(self):
        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
        )


class ParentInviteEmailForm(forms.Form):
    """The optional "email this link" action on parent_invite_player -- ParentInvite itself
    doesn't carry a pre-set invitee email, so this is where one gets typed in."""

    email = forms.EmailField(label="Email address")
