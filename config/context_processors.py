# Single source of truth for the club's general inbox -- injected into every
# template's context (see TEMPLATES in settings.py) since it's shown in the
# site footer on every page, not just one view's context.
# TODO: placeholder -- replace with the club's real contact address.
GENERAL_CONTACT_EMAIL = "info@choiceselectbaseball.com"


def general_contact_email(request):
    return {"general_contact_email": GENERAL_CONTACT_EMAIL}
