# Changelog

Running log of changes made to this repo, newest first. Short description + files touched per entry.
Not a replacement for git history — this is meant to be skimmable without running `git log`.

## 2026-09-22 — Split TryoutSignup names into first/last

`TryoutSignup.player_name` and `.parent_name` were single full-name fields — inconsistent with
`accounts.User`/`accounts.Player`, which already split first/last. Split them to match, with a data
migration backfilling any existing rows (splits on the last space) and `*_full_name` properties for
display. Updated the admin, form, and signup template/CSS to match (first/last shown as a
side-by-side pair).

Files:
- `apps/tryouts/models.py` — `player_name`/`parent_name` → `player_first_name`/`player_last_name`/
  `parent_first_name`/`parent_last_name`; added `player_full_name`/`parent_full_name` properties.
- `apps/tryouts/migrations/0002_split_names.py` — new. Adds the new fields, backfills from the old
  ones via `RunPython` (reversible), drops the old fields.
- `apps/tryouts/admin.py` — `list_display`/`search_fields` updated to the new fields.
- `apps/tryouts/forms.py` — form fields/labels updated.
- `apps/tryouts/templates/tryouts/signup.html` — first/last name shown as a paired row.
- `static/css/main.css` — added `.form-row` for side-by-side field pairs.
- `CLAUDE.md` — documented the first/last-name convention.

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
