from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone


def send_response_invite_email(invite, request):
    """
    Emails the family the Accept/Decline (or outcome-only) link for
    `invite` -- the automated "send" action layered on top of the existing
    copy/paste link, per CLAUDE.md's roster-promotion plan step 6. Needs
    `request` to build an absolute URL, same as
    apps.accounts.views.admin_tryout_response_invite's own link generation.
    """
    signup = invite.signup
    invite_url = request.build_absolute_uri(reverse("tryouts:respond", args=[invite.token]))
    subject = f"Try-Out Update for {signup.player_first_name} — {signup.team.name}"
    body = render_to_string(
        "emails/tryout_response_invite.txt",
        {"signup": signup, "invite": invite, "invite_url": invite_url},
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [signup.parent_email])
    invite.emailed_at = timezone.now()
    invite.save(update_fields=["emailed_at"])
