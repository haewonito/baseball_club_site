from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def send_parent_invite_email(invite, request):
    """
    Emails the second-parent invite link for `invite` to
    invite.invitee_email -- the optional "email it" action alongside the
    existing copy/paste link on parent_invite_player. Needs `request` to
    build an absolute URL. Called from
    apps.accounts.views.parent_invite_send_email, which owns marking
    invite.emailed_at -- this function only sends.
    """
    invite_url = request.build_absolute_uri(reverse("accounts:invite_claim", args=[invite.token]))
    subject = f"You're invited to connect with {invite.player}'s account"
    body = render_to_string(
        "emails/parent_invite.txt",
        {"invite": invite, "invite_url": invite_url},
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [invite.invitee_email])
