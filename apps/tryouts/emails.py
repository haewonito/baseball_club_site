from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


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
