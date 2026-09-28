from django.conf import settings
from django.core.mail import EmailMessage, get_connection, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from config.context_processors import GENERAL_CONTACT_EMAIL


def send_response_invite_email(invite, request):
    """
    Emails the family the Accept/Decline (or outcome-only) link for
    `invite`. Needs `request` to build an absolute URL. Called from
    apps.accounts.views.coach_tryout_send_email, which owns marking the
    signup's decision as emailed (TryoutSignup.decision_emailed_at) --
    this function only sends, it doesn't record anything itself.
    """
    signup = invite.signup
    invite_url = request.build_absolute_uri(reverse("tryouts:respond", args=[invite.token]))
    subject = f"Try-Out Update for {signup.player_first_name} — {signup.team.name}"
    body = render_to_string(
        "emails/tryout_response_invite.txt",
        {"signup": signup, "invite": invite, "invite_url": invite_url},
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [signup.parent_email])


def send_signup_confirmation_email(signup):
    """
    Confirms a public try-out sign-up to the parent who submitted it. Called
    from apps.tryouts.views.signup right after the signup is saved; the
    caller catches failures so a mail problem never loses a sign-up.
    """
    from .models import TryoutYearSettings

    next_tryout_date = TryoutYearSettings.get_next_tryout_date()
    if next_tryout_date and next_tryout_date < timezone.localdate():
        next_tryout_date = None
    subject = f"Try-Out Sign-Up Received — {signup.player_first_name} ({signup.team.name})"
    body = render_to_string(
        "emails/tryout_signup_confirmation.txt",
        {
            "signup": signup,
            "next_tryout_date": next_tryout_date,
            "contact_email": GENERAL_CONTACT_EMAIL,
        },
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [signup.parent_email])


# Resend's batch endpoint takes at most 100 messages per call.
MASS_EMAIL_BATCH_SIZE = 100


class MassEmailError(Exception):
    """A mass send failed partway. `sent` lists the addresses that did go out."""

    def __init__(self, sent, cause):
        super().__init__(str(cause))
        self.sent = sent


def send_tryout_mass_email(subject, body, emails, reply_to):
    """
    Sends one copy of the message to each address in `emails`, so families
    never see each other's addresses. Returns the addresses sent to, or
    raises MassEmailError (with the ones already sent) if a batch fails.

    On Resend (anymail), each batch of up to 100 is a single API call:
    an empty merge_data turns a multi-recipient message into Resend's batch
    send, one message per `to` address. That avoids one API call per family,
    which Resend's rate limit would make slow enough to time out the request.
    Any other backend (console locally) gets one message per address over a
    single connection -- never one message with every address in `to`.
    """
    sent = []
    try:
        if settings.EMAIL_BACKEND.startswith("anymail."):
            for start in range(0, len(emails), MASS_EMAIL_BATCH_SIZE):
                batch = emails[start : start + MASS_EMAIL_BATCH_SIZE]
                message = EmailMessage(
                    subject, body, settings.DEFAULT_FROM_EMAIL, to=batch, reply_to=reply_to
                )
                message.merge_data = {}
                message.send()
                sent.extend(batch)
        else:
            with get_connection() as connection:
                for email in emails:
                    EmailMessage(
                        subject,
                        body,
                        settings.DEFAULT_FROM_EMAIL,
                        to=[email],
                        reply_to=reply_to,
                        connection=connection,
                    ).send()
                    sent.append(email)
    except Exception as exc:
        raise MassEmailError(sent, exc) from exc
    return sent
