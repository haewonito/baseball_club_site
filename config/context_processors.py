# Single source of truth for the club's general inbox -- injected into every
# template's context (see TEMPLATES in settings.py) since it's shown in the
# site footer on every page, not just one view's context.
# Forwarded to a real inbox via Cloudflare Email Routing (see CLAUDE.md).
GENERAL_CONTACT_EMAIL = "info@choiceselectleague.org"


def general_contact_email(request):
    return {"general_contact_email": GENERAL_CONTACT_EMAIL}
