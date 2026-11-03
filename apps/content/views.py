import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import BugReportForm
from .models import BugReport

logger = logging.getLogger(__name__)


def report_bug(request):
    """Footer "report a problem" form: emails the website manager, at most BUG_REPORT_DAILY_LIMIT a day."""
    limit_reached = BugReport.limit_reached()
    sent = request.GET.get("sent") == "1"
    send_failed = False

    if request.method == "POST" and not limit_reached:
        form = BugReportForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["website"]:
                # Honeypot filled in: say thanks and send nothing.
                return redirect(f"{reverse('report_bug')}?sent=1")
            page = form.cleaned_data["page"]
            if page and not url_has_allowed_host_and_scheme(page, allowed_hosts=None):
                page = ""
            user = request.user if request.user.is_authenticated else None
            report = BugReport.objects.create(
                message=form.cleaned_data["message"],
                reporter_email=form.cleaned_data["reporter_email"],
                page=page,
                user=user,
            )
            try:
                email = EmailMessage(
                    subject="Website problem report",
                    body=render_to_string(
                        "emails/bug_report.txt",
                        {
                            "report": report,
                            "user": user,
                            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                            "site_url": settings.SITE_URL,
                        },
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[settings.BUG_REPORT_EMAIL],
                    reply_to=[report.reporter_email] if report.reporter_email else None,
                )
                email.send()
            except Exception:
                logger.exception("Could not send bug report %s", report.pk)
                report.delete()  # a report that never went out must not use up today's limit
                send_failed = True
            else:
                return redirect(f"{reverse('report_bug')}?sent=1")
    else:
        form = BugReportForm(initial={"page": request.GET.get("page", "")[:300]})

    return render(
        request,
        "content/report_bug.html",
        {"form": form, "limit_reached": limit_reached, "sent": sent, "send_failed": send_failed},
    )
