# Changelog

Running log of changes made to this repo, newest first. Short description + files touched per entry.
Not a replacement for git history — this is meant to be skimmable without running `git log`.

## 2026-09-22 — Try-out sign-up form (first real page)

Built the public try-out sign-up page end to end: form, view, URLs, and the shared page shell/styles
it introduces. Verified live via a real POST against the dev server + Postgres (not just
`manage.py check`) — confirmed `tryout_year` auto-computes correctly and validation errors render.

Files:
- `apps/tryouts/forms.py` — new. `TryoutSignupForm` (`ModelForm`, public fields only).
- `apps/tryouts/views.py` — new. `signup` + `signup_success` views.
- `apps/tryouts/urls.py` — wired `/try-outs/` and `/try-outs/thanks/`.
- `apps/tryouts/templates/tryouts/signup.html` — new.
- `apps/tryouts/templates/tryouts/signup_success.html` — new.
- `templates/base.html` — new. Shared header/footer/messages shell for all future pages.
- `templates/partials/_form_field.html` — new. Reusable bound-field include (label/help/error markup).
- `static/css/main.css` — new. Implements the black/white/red visual design direction site-wide.
- `CLAUDE.md` — updated site map note to point at what's now built.

## 2026-09-22 — CLAUDE.md created

Initial `CLAUDE.md` documenting commands, domain model, and known gaps for future Claude Code
sessions. Since expanded (in later sessions, not tracked here in detail) with deployment gotchas,
visual design direction, and the site map.

Files:
- `CLAUDE.md` — new.
