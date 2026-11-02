import logging

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.fees.models import Payment

from ..emails import send_parent_invite_email
from ..forms import (
    InviteClaimSignupForm,
    ParentInviteEmailForm,
    PlayerGalleryPhotoForm,
    downsize_image,
)
from ..models import (
    MAX_LINKED_ADULTS_PER_PLAYER,
    ParentInvite,
    ParentPlayerLink,
    Player,
    PlayerGalleryPhoto,
    Role,
    UserRole,
)

logger = logging.getLogger(__name__)


@login_required
def dashboard_parent(request):
    if not request.user.is_parent:
        raise PermissionDenied

    links = (
        ParentPlayerLink.objects.filter(parent=request.user, removed_at__isnull=True)
        .select_related("player", "player__team")
        .prefetch_related(
            "player__fees__payments",
            Prefetch(
                "player__parent_links",
                queryset=ParentPlayerLink.objects.filter(removed_at__isnull=True).select_related(
                    "parent"
                ),
                to_attr="active_links",
            ),
        )
        .order_by("player__last_name", "player__first_name")
    )
    now = timezone.now()
    cards = []
    for link in links:
        player = link.player
        next_event = None
        if player.team:
            next_event = player.team.events.filter(start_datetime__gte=now).order_by("start_datetime").first()
        # Team-wide fees fan out into per-player Fee rows at creation time
        # (see admin_fee_add), so a plain player.fees.all() already picks
        # them up -- no separate team-fee handling needed here.
        balance = sum(fee.balance for fee in player.fees.all())
        primary_link = next((l for l in player.active_links if l.is_primary), None)
        cards.append(
            {
                "player": player,
                "next_event": next_event,
                "balance": balance,
                "primary_link": primary_link,
                "is_primary": link.is_primary,
                # Adults the current primary could hand "primary" to.
                "other_links": [l for l in player.active_links if l.pk != link.pk],
            }
        )

    return render(request, "accounts/dashboard_parent.html", {"cards": cards})


@login_required
def parent_player_payments(request, player_id):
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player
    fees = list(player.fees.all())
    total_due = sum(fee.amount_due for fee in fees)

    payments = Payment.objects.filter(fee__player=player).select_related("fee").order_by("paid_at", "recorded_at")
    running_total = 0
    rows = []
    for payment in payments:
        running_total += payment.amount
        rows.append({"payment": payment, "running_total": running_total})

    return render(
        request,
        "accounts/parent_player_payments.html",
        {
            "player": player,
            "rows": rows,
            "total_due": total_due,
            "total_paid": running_total,
            "balance": total_due - running_total,
        },
    )


@login_required
def parent_player_profile_edit(request, player_id):
    """Profile editing now happens inline on the player page (teams.views.
    player_detail, which does the permission check); this URL only keeps old
    links and bookmarks working."""
    return redirect(reverse("teams:player_detail", args=[player_id]) + "#profile")


def _get_gallery_player_or_403(user, player_id):
    """Gallery editing is linked-parents-only -- no admin override here,
    unlike the profile form on player_detail (see PlayerGalleryPhoto)."""
    player = get_object_or_404(Player, pk=player_id)
    if not ParentPlayerLink.objects.filter(
        parent=user, player=player, removed_at__isnull=True
    ).exists():
        raise PermissionDenied
    return player


@login_required
@require_POST
def parent_player_gallery_add(request, player_id):
    player = _get_gallery_player_or_403(request.user, player_id)
    form = PlayerGalleryPhotoForm(request.POST, request.FILES, player=player)
    if form.is_valid():
        for image in form.cleaned_data["images"]:
            PlayerGalleryPhoto.objects.create(
                player=player, image=downsize_image(image), uploaded_by=request.user
            )
        count = len(form.cleaned_data["images"])
        messages.success(request, f"Added {count} photo{'s' if count != 1 else ''}.")
    else:
        for error in form.errors.get("images", []):
            messages.error(request, error)
    return redirect(reverse("teams:player_detail", args=[player.pk]) + "#gallery")


@login_required
@require_POST
def parent_player_gallery_delete(request, player_id, photo_id):
    player = _get_gallery_player_or_403(request.user, player_id)
    photo = get_object_or_404(PlayerGalleryPhoto, pk=photo_id, player=player)
    # Removes the stored file too (R2 or ./media) -- deleting the row alone
    # would leave it orphaned in storage.
    photo.image.delete(save=False)
    photo.delete()
    messages.success(request, "Photo deleted.")
    return redirect(reverse("teams:player_detail", args=[player.pk]) + "#gallery")


@login_required
def parent_invite_player(request, player_id):
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player

    invite = _open_invite_for(player, request.user)
    if request.method == "POST" and not invite:
        # At most MAX_LINKED_ADULTS_PER_PLAYER adults per kid, counting
        # open invites, so the page offers "Generate" only while a slot is left.
        if ParentInvite.slots_left(player) > 0:
            invite = ParentInvite.objects.create(player=player, created_by=request.user)
        else:
            messages.error(
                request,
                f"{player.first_name} already has the most adults allowed. Contact the club to add someone else.",
            )

    invite_url = None
    email_form = None
    if invite:
        invite_url = request.build_absolute_uri(reverse("accounts:invite_claim", args=[invite.token]))
        # The link itself is always shown (below); this is just the extra
        # "email it" option alongside it -- prefill with whoever it was
        # last sent to, so a resend doesn't need retyping the address.
        email_form = ParentInviteEmailForm(initial={"email": invite.invitee_email})

    linked_count = player.parent_links.filter(removed_at__isnull=True).count()
    return render(
        request,
        "accounts/parent_invite.html",
        {
            "player": player,
            "invite": invite,
            "invite_url": invite_url,
            "email_form": email_form,
            "linked_count": linked_count,
            "max_adults": MAX_LINKED_ADULTS_PER_PLAYER,
            "can_invite": ParentInvite.slots_left(player) > 0,
        },
    )


def _open_invite_for(player, user):
    """`user`'s current usable invite for `player`, if any -- a parent has
    at most one open invite per kid at a time."""
    return (
        ParentInvite.open_invites()
        .filter(player=player, created_by=user)
        .order_by("-created_at")
        .first()
    )


@login_required
@require_POST
def parent_invite_cancel(request, player_id):
    """Cancels the logged-in parent's open invite link for this kid. Only
    possible before anyone has used it -- a used link is already a
    parent-player link, which only an admin can remove."""
    if not request.user.is_parent:
        raise PermissionDenied
    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    invite = _open_invite_for(link.player, request.user)
    if invite:
        invite.cancelled_at = timezone.now()
        invite.save(update_fields=["cancelled_at"])
        messages.success(request, "Invite link cancelled. It can no longer be used.")
    else:
        messages.error(request, "There's no unused invite link to cancel.")
    return redirect("accounts:parent_invite_player", player_id=link.player_id)


@login_required
@require_POST
def parent_make_primary(request, player_id):
    """
    The kid's current primary parent hands "primary" to another adult
    linked to the same kid (ParentPlayerLink.save un-primaries their own
    link). Only the current primary can do this; admins use Django admin.
    """
    if not request.user.is_parent:
        raise PermissionDenied
    own_link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    if not own_link.is_primary:
        raise PermissionDenied
    new_link = get_object_or_404(
        ParentPlayerLink.objects.select_related("parent"),
        pk=request.POST.get("link_id"),
        player_id=player_id,
        removed_at__isnull=True,
    )
    if new_link.pk != own_link.pk:
        new_link.is_primary = True
        new_link.save(update_fields=["is_primary"])
        messages.success(
            request,
            f"{new_link.parent} is now {own_link.player.first_name}'s primary parent.",
        )
    return redirect("accounts:dashboard_parent")


@login_required
@require_POST
def parent_invite_send_email(request, player_id):
    """The optional "email it" action layered on top of parent_invite_player's copy/paste link -- doesn't replace it."""
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player

    invite = _open_invite_for(player, request.user)
    if not invite:
        raise PermissionDenied

    email_form = ParentInviteEmailForm(request.POST)
    if not email_form.is_valid():
        messages.error(request, "Enter a valid email address.")
        return redirect("accounts:parent_invite_player", player_id=player.pk)

    invite.invitee_email = email_form.cleaned_data["email"]
    invite.save(update_fields=["invitee_email"])

    try:
        send_parent_invite_email(invite, request)
    except Exception:
        logger.exception("Parent invite email failed for invite %s", invite.pk)
        # Parents see this, so point them at the copy/paste link rather
        # than at server configuration they can't do anything about.
        messages.error(
            request,
            "Couldn't send the email right now. You can still copy the link above and send it yourself.",
        )
    else:
        invite.emailed_at = timezone.now()
        invite.save(update_fields=["emailed_at"])
        messages.success(
            request,
            f"Emailed the invite link to {invite.invitee_email}. "
            "If they don't see it, ask them to check their spam folder.",
        )

    return redirect("accounts:parent_invite_player", player_id=player.pk)


def invite_claim(request, token):
    """
    Public -- no login required to view. Whoever holds this link can either
    confirm with their existing account (if already logged in) or create a
    new one on the spot; there's no pre-set invitee email on ParentInvite,
    so this is the only way to tie a specific person to the claim.
    """
    invite = get_object_or_404(
        ParentInvite.objects.select_related("player", "created_by"), token=token
    )

    if not invite.is_valid:
        return render(request, "accounts/invite_invalid.html", {"invite": invite})

    # Re-checked here, not just when the link was made: another adult may
    # have been linked since. Someone already linked to the kid isn't
    # adding anyone, so they're never blocked.
    already_linked = request.user.is_authenticated and invite.player.parent_links.filter(
        parent=request.user, removed_at__isnull=True
    ).exists()
    at_cap = (
        invite.player.parent_links.filter(removed_at__isnull=True).count()
        >= MAX_LINKED_ADULTS_PER_PLAYER
    )
    if at_cap and not already_linked:
        return render(request, "accounts/invite_invalid.html", {"invite": invite, "full": True})

    if request.user.is_authenticated:
        if request.method == "POST":
            _complete_invite_claim(invite, request.user)
            return redirect("accounts:dashboard")
        return render(request, "accounts/invite_claim_confirm.html", {"invite": invite})

    if request.method == "POST":
        form = InviteClaimSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            _complete_invite_claim(invite, user)
            auth_login(request, user)
            return redirect("accounts:dashboard")
    else:
        form = InviteClaimSignupForm()
    return render(request, "accounts/invite_claim_signup.html", {"invite": invite, "form": form})


def _complete_invite_claim(invite, user):
    # Only an *active* link counts: an adult whose earlier link was removed
    # gets a new one (removed links stay as history).
    ParentPlayerLink.objects.get_or_create(
        parent=user,
        player=invite.player,
        removed_at__isnull=True,
        defaults={"created_by": invite.created_by},
    )
    invite.claimed_at = timezone.now()
    invite.claimed_by = user
    invite.save(update_fields=["claimed_at", "claimed_by"])
    parent_role, _ = UserRole.objects.get_or_create(role=Role.PARENT)
    user.roles.add(parent_role)
