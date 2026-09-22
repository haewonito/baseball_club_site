# Changelog

Running log of changes made to this repo, newest first. Short description + files touched per entry.
Not a replacement for git history — this is meant to be skimmable without running `git log`.

## 2026-09-22 — Player positions surfaced in the admin

`teams.PlayerPosition` (the player↔position join table, already on the canonical `Position` list as
of the previous entry) existed but was only reachable as its own separate top-level admin page —
not visible when editing a Player. Added it as an inline on the Player admin page instead, same
pattern as the `TryoutSignupPosition` inline. No schema change (the model already existed).

Files:
- `apps/accounts/admin.py` — added `PlayerPositionInline` to `PlayerAdmin`; added a
  `positions_display` column to the Player list view.

## 2026-09-22 — Positions locked to one canonical, code-based list

`teams.Position` and the tryout form's free-text `positions` field were two separate, inconsistent
position vocabularies (and the free-text one had real data like `'short stop, catcher, pitcher'`).
Unified both under one `Position` enum (`LP`/`RP`/`C`/`B1`/`B2`/`B3`/`SS`/`LF`/`CF`/`RF`), and turned
the sign-up form's position field into a proper normalized multi-select (checkbox group) backed by a
new join table, instead of free text.

Files:
- `apps/teams/models.py` — `Position` choices replaced with the canonical list (pitcher split
  LP/RP, outfield split LF/CF/RF, base codes changed 1B/2B/3B → B1/B2/B3).
- `apps/teams/migrations/0002_canonical_position_list.py` — new. Choices-only change; `PlayerPosition`
  had 0 existing rows so no data migration needed.
- `apps/tryouts/models.py` — removed the free-text `positions` field; added `TryoutSignupPosition`
  (FK to `TryoutSignup` + `position` choice field referencing `teams.Position`) and a
  `positions_display` property.
- `apps/tryouts/migrations/0003_split_positions.py` — new. Backfills existing free text via a
  best-effort alias map (handles things like `"short stop"` → `SS`); anything ambiguous (bare
  `"pitcher"`/`"outfield"`, no way to infer handedness/side) is left unmapped with a printed note for
  manual follow-up in the admin. Reversible — verified full forward/reverse/forward round trip.
- `apps/tryouts/forms.py` — `positions` is now a `MultipleChoiceField` + `CheckboxSelectMultiple`
  over `Position.choices`, saved into `TryoutSignupPosition` rows via an overridden `save()`.
- `apps/tryouts/admin.py` — added a `TryoutSignupPositionInline`; `list_display`/`search_fields`
  updated to the new fields.
- `static/css/main.css` — excluded checkboxes/radios from the blanket input styling; added a compact
  grid layout for the position checkbox group.
- `CLAUDE.md` — documented the one-canonical-position-list convention.

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
