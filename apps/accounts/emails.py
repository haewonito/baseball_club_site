from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core import signing
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


VERIFY_SALT = "accounts.verify-email"
VERIFY_MAX_AGE = 3 * 24 * 60 * 60


def make_verification_token(user):
    # The email is in the payload so changing it invalidates old links.
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=VERIFY_SALT)


def read_verification_token(token):
    """Returns the payload dict, or None if the token is bad or older than 3 days."""
    try:
        return signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
    except signing.BadSignature:
        return None


def send_verification_email(user, request):
    """Emails the confirm-your-address link to a newly registered user. Callers own verification_sent_at."""
    verify_url = request.build_absolute_uri(
        reverse("accounts:verify_email", args=[make_verification_token(user)])
    )
    body = render_to_string("emails/verify_email.txt", {"user": user, "verify_url": verify_url})
    send_mail(
        "Confirm your email for Choice Select", body, settings.DEFAULT_FROM_EMAIL, [user.email]
    )
