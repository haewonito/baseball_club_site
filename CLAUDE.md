# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Django 5.0 site for a youth baseball club. It is a **models-and-admin scaffold**, not a running app:
every `apps/*/urls.py` has an empty `urlpatterns`, there are no views, no templates (the `templates/`
dir is empty), and no tests. The work in front of you is almost always "build the view/template layer
on top of models that already exist."

The scaffold was hand-written rather than produced by `django-admin startproject` (the authoring
environment had no network), so treat generated-file conventions as approximations and verify against
real Django behavior. The README also references a planning doc `baseball_club_website_plan.md` that
is **not in this repo** — don't assume it's available.

**The app is already deployed and working on Railway** (Postgres addon, migrations applied,
`/admin/` reachable and logging in successfully) — this isn't a "get it deployed" task, it's "keep
deploys working while adding features." See Deployment gotchas below before touching anything
deploy-related; several non-obvious things had to be fixed to get there.

## Commands

`venv/` is gitignored — it exists on this checkout but won't exist after a fresh clone. Bootstrap it
with:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

```bash
source venv/bin/activate

python manage.py runserver
python manage.py migrate
python manage.py makemigrations <app_label>   # app labels are accounts, teams, tryouts, schedule, fees
python manage.py createsuperuser
python manage.py collectstatic                # needed before running with DEBUG=False

python manage.py test                         # no tests exist yet
python manage.py test apps.fees.tests.FeeBalanceTests.test_partial   # single test, once tests exist
```

Local Postgres is required — there is no SQLite fallback, and `DATABASE_URL` has no default in
`.env.example`'s absence, so `config("DATABASE_URL")` will raise if `.env` is missing.

```bash
brew services start postgresql@16 && createdb baseball_club
```

Local Postgres runs via Homebrew, deliberately not Docker — Docker-based Postgres setups caused
enough friction on this machine (M1 Mac) that Homebrew was chosen specifically to avoid that class of
problem. Don't suggest a docker-compose Postgres setup without a good reason.

## Configuration

`config/settings.py` reads every environment-dependent value through `python-decouple`'s `config()`,
which resolves from `.env` locally and from real env vars on Railway — the same variable names in both
places. `SECRET_KEY` and `DATABASE_URL` are required with no default; the app won't start without them.

Two settings behave as feature switches:

- `USE_R2` — `True` routes uploads (coach photos, future media) to Cloudflare R2 through
  django-storages' S3 backend; `False` writes to `./media` and is the local default.
- `ALLOWED_HOSTS` — `CSRF_TRUSTED_ORIGINS` is *derived* from it (every non-localhost host becomes
  `https://<host>`). A production CSRF failure is usually a missing entry here, not a CSRF-specific
  setting. `SECURE_PROXY_SSL_HEADER` is also set (Railway terminates HTTPS at its edge proxy and
  forwards to the app over plain HTTP internally — without this setting Django thinks every request
  is insecure, which breaks CSRF/session cookies even with `ALLOWED_HOSTS` correct).

`Pillow` is a required dependency (in `requirements.txt`) even though nothing in this repo obviously
needs it at a glance — `CoachProfile.photo` is an `ImageField`, which Django can't validate/process
without it. If a future `ImageField` gets added and installs fail with a Pillow-related error, that's
why.

## Deployment gotchas (Railway)

These cost real time to work out and aren't obvious from Railway's docs or defaults:

- **Static files must NOT be collected in the Pre-Deploy Step.** Railway's Pre-Deploy Step runs in a
  separate, ephemeral container that gets discarded before the actual runtime container starts —
  anything `collectstatic` writes to disk there is gone by the time gunicorn boots, causing
  `{% static %}` template tags to fail (missing manifest entry) and a 500 on every page, including
  `/admin/login/`. Fix: `collectstatic` runs as part of the **Custom Start Command** instead, chained
  right before gunicorn, in the same container that stays alive:
  `python manage.py collectstatic --noinput && gunicorn config.wsgi --log-file -`
  The Pre-Deploy Step should contain only `python manage.py migrate` (migrations are safe there since
  they write to the external Postgres database, not local disk).
- **Variables and the Pre-Deploy Step must be set on the Django service, not the Postgres service.**
  Railway shows both as boxes on the same project canvas and it's easy to click the wrong one — if
  `SECRET_KEY` mysteriously "isn't found" despite being visibly set somewhere, check which service it
  was actually added to.
- **`DATABASE_URL`'s default value (`postgres.railway.internal`) only resolves inside Railway's
  private network.** It works fine for the deployed app itself, but running Django management
  commands *from a local machine* against the production database (e.g. `createsuperuser` on prod)
  needs the Postgres service's `DATABASE_PUBLIC_URL` instead, which requires enabling the TCP Proxy
  under the Postgres service's Settings → Networking first (off by default). Also: `railway run
  <command>` re-injects Railway's own service variables and will silently overwrite a manually-set
  `DATABASE_URL` override — for a one-off prod command with a substituted URL, run it as a plain local
  command instead (`DATABASE_URL="..." python manage.py createsuperuser`), not through `railway run`.
- Railway's dashboard sometimes displays a variable's raw `${{Service.VAR}}` reference template
  rather than its resolved value — if a copied value contains literal `${{...}}` syntax, it hasn't
  been resolved; get the real value via `railway variables` with the CLI targeted at that specific
  service (`railway service` to switch), not by copying what the dashboard shows.

## Visual design direction

Club colors are black, white, and red (the club's logo is red; on-field jersey colors alternate
white/black for home/away, which has no bearing on the website). The established direction, already
applied to several wireframed/mocked-up pages, and expected to carry through anything new:

- **Black** used structurally — header/footer bars, nav — not as a general text color.
- **White** as the dominant surface for actual content (cards, tables), with light gray hairlines
  rather than heavy borders.
- **Red** reserved for meaning, not decoration — status badges, key actions/links, confirm buttons,
  "this needs attention" indicators. Pale-red tints for informational status (e.g. "new",
  "partially paid"); solid red for primary actions.
- Overall: clean, minimalist, generous whitespace. Avoid a busy or heavily-bordered look.

## Site map (target page structure — none of this exists as views/templates yet)

**Public (no login):** Home (mission blurb + upcoming try-out banner within 30 days) · Try-Outs
(process info + signup form) · Schedule (filterable by team) · Teams index → Team detail (roster w/
positions, coaching staff w/ head/assistant labels, filtered schedule) · Coaches index (optional) ·
Location/Directions · Contact · Login / Invite claim

**Parent (logged in):** Dashboard — per-kid card (next event, fee balance) → click-through to a full
payment history page (date/method/amount table + running total) — not just inline totals · Invite
second parent · Schedule (pre-filtered to their team)

**Coach (logged in):** Dashboard with a **team switcher** if linked to multiple teams (shows role —
head/assistant — per team, though permissions don't differ by role) · Roster (view/edit, incl.
positions) · Practice Schedule (edit) · Tournament Schedule (view-only) · Try-Out Sign-Ups
(view-only, all teams, all years)

**Admin (logged in):** Dashboard · Try-Out Sign-Ups — list w/ year filter, status change as a
**dropdown with a confirmation dialog** before it commits (this is the HTMX flow — see
`TryoutStatusChange` in the model layer) → per-kid detail · Fees & Payments — create/edit, record
payments, outstanding-balance dashboard · Teams — create/edit, assign coaches · Schedule Management
· Users & Linking — role assignment, parent-player link management/history · Coach Bios · Site
Content

The public try-out signup form is built: `apps/tryouts/{forms,views,urls}.py` +
`apps/tryouts/templates/tryouts/{signup,signup_success}.html`, at `/try-outs/`. It also established
the shared `templates/base.html` shell, `templates/partials/_form_field.html` (include per bound
field to get label/help/error markup consistently), and `static/css/main.css` implementing the visual
design direction above — reuse these for the next page rather than duplicating field/error markup.
Everything else in the site map is still unbuilt.

## Domain model

Five apps under `apps/` (note the package prefix: `INSTALLED_APPS` uses `apps.accounts`, etc., and
each `AppConfig.name` matches).

**Person names are always stored as separate first/last name fields, never a single full-name
field** — `accounts.User` (via `AbstractUser`), `accounts.Player`, and `tryouts.TryoutSignup`
(`player_first_name`/`player_last_name`, `parent_first_name`/`parent_last_name`) all follow this.
Keep it consistent if a new model gains a person-name field. Where a display string is convenient,
add a `*_full_name` property that joins them (see `TryoutSignup.player_full_name`) rather than
storing the joined form.

**Baseball positions are a single canonical, code-based enum, never free text** —
`apps.teams.models.Position` (`LP`/`RP`/`C`/`B1`/`B2`/`B3`/`SS`/`LF`/`CF`/`RF`) is the one list used
everywhere a position is recorded: `teams.PlayerPosition` (roster) and `tryouts.TryoutSignupPosition`
(sign-up form) both FK/reference it. Never add a plain `CharField`/free-text field for a position —
use a join-table row against `Position` instead, the way both of those do.

**accounts** — `AUTH_USER_MODEL = "accounts.User"`. Roles are deliberately many-to-many rather than a
field: `User.roles` → `UserRole`, where `UserRole.role` is **unique**, so `UserRole` rows are shared
singletons (one "admin" row that many users point at), not per-user grants. This exists because the
league owner is simultaneously an Admin and a head coach. Use `user.has_role()` / `.is_admin` /
`.is_coach` / `.is_parent` as the basis for any permission work — each hits the DB, so prefetch
`roles` in list views.

`Player` is *not* a `User` — kids don't log in. Parents reach players through `ParentPlayerLink`,
which is **soft-deleted** (`removed_at`/`removed_by`) to preserve an audit log; the uniqueness
constraint is conditional on `removed_at__isnull=True`, so always filter on that when querying active
links. `ParentInvite` is the self-service second-parent flow: UUID token, 14-day expiry, single claim.
Both sending and claiming must display the "this person will see the kid's private info" warning.

**teams** — `TeamCoach` joins coaches to teams many-to-many (a coach can hold multiple teams). Its
`role` (head/assistant) is **display-only** — both levels carry identical permissions. `CoachProfile`
holds bio/photo, kept separate from the auth record. `PlayerPosition` is the player↔position M2M.

**tryouts** — public, no-login submissions. `TryoutSignup.tryout_year` is computed on first save by
`compute_tryout_year()`: submissions on or after the cutoff (default Sept 1) are tagged for *next*
year. The cutoff comes from the `TryoutYearSettings` singleton row if one exists, otherwise from
`settings.DEFAULT_TRYOUT_YEAR_CUTOFF_MONTH/DAY`. `TryoutStatusChange` is the status audit trail and
pairs with a confirmation dialog in the intended UX — status edits should write a row, not just
mutate `status`.

**schedule** — one `Event` model covers both practices and tournaments via `event_type`. Recurring
practices are materialized as individual rows by bulk-create; there is no series/recurrence-rule
concept. `status` drives a cancellation banner on the public schedule.

**fees** — ledger-style. `Fee` is what's owed, `Payment` rows are manually recorded against it. There
is **no payment processing and no card data** — if online payment is ever added it goes through
Stripe/Square. `Fee.amount_paid`/`.balance`/`.status` are Python properties that iterate
`self.payments.all()`, so any list of fees needs `prefetch_related("payments")` to avoid N+1, and
these cannot be used in `filter()`/`order_by()`.

A `Fee` with `player=None` and a `team` set represents a team-wide fee; how that expands into
per-player ledger rows is an open decision.

## Known gaps to build

- No permission layer yet. The rules to enforce: a coach edits their own team's roster, is view-only
  on tournaments, and never sees fees unless they also hold the Admin role. One specific head coach
  (the league owner) holds both Coach and Admin roles for exactly this reason — don't special-case him
  in code, the many-to-many roles model already covers it.
- `django-htmx` is installed and middleware-wired but unused. The flows designed for it are the
  tryout status dropdown + confirmation, payment recording, and the invite-link claim.
- No GameChanger ICS sync. If a subscribable feed is confirmed, `Event` gains a `source` field
  (manual vs. synced) and the coach/admin edit UI narrows to an override layer for cancellations.
- No views/templates/tests at all yet — see Site map above for the target structure.

## Future ideas (nice-to-have, not scheduled)

- **Season roll-up + post-tryout decision → roster workflow.** Right now nothing happens after a
  signup reaches `status=attended`, and promoting players between seasons means editing each `Player`
  row by hand. Refined design below (this supersedes two earlier separate notes on these ideas --
  they turned out to be the same underlying mechanism, worked out across a planning conversation):

  1. **Pre-create next season's teams before announcing tryouts.** E.g. before opening 2027-2028
     tryouts for 11U and 13U, an admin creates `Team` rows for "Choice Select 11U (2027-2028)" and
     "Choice Select 13U (2027-2028)" -- and can assign next season's head coach to each via
     `TeamCoach` right away, before a single signup comes in.
  2. **New teams aren't public until ready.** Add `Team.is_public` (default `True`, so nothing
     currently live changes), set to `False` on newly pre-created teams so they don't show up on the
     public Teams/Coaches pages with an empty roster months before the season starts.
     `team_index`/`team_detail` filter on it; admin flips it once the roster's finalized.
  3. **Parents pick the team on the sign-up form**, not an inferred division. Add
     `TryoutSignup.team` (FK to `Team`), and a team-select field on the public sign-up form scoped to
     whichever teams are currently open for tryouts (its own flag, e.g. `Team.accepting_tryouts` --
     distinct from `is_public`, since a team can accept signups before it's ready to be shown
     publicly). Also resolves the age-cutoff-borderline-kid case more simply than automatic inference
     ever did -- the parent just picks.
  4. **`TryoutSignup.tryout_year`'s cutoff-date computation (`compute_tryout_year`) gets retired**
     once every signup is explicitly tied to a team -- `tryout_year` becomes simply
     `signup.team.season_year`, no heuristic needed.
  5. **Coach decides, per signup**: add `TryoutSignup.coach_decision` (`undecided` default →
     `invite` / `maybe` / `not_selected`), with an audit trail model `TryoutDecisionChange` mirroring
     `TryoutStatusChange`. Separate axis from `status` (contact/attendance logistics). `maybe` is
     internal-only -- never shown to the family; must resolve to `invite`/`not_selected` before
     reveal. Since every signup now has an explicit `team`, "who's allowed to decide" reuses the
     existing `coach_assignments__coach=user` permission pattern already used for roster/practice
     editing -- no new permission model needed.
  6. **Batch reveal, not per-player auto-send.** `decisions_finalized` flag, scoped per team (not
     per tryout year overall) so e.g. 11U families aren't held up by 13U's evaluation running long.
  7. **Family responds without logging in.** Reuse `ParentInvite`'s pattern (UUID token, expiring,
     single-use) for a new public page `/try-outs/respond/<token>/` with Accept/Decline. Add
     `TryoutSignup.family_response` (`pending` → `accepted`/`declined`). On accept, let them set a
     password in the same flow, so responding and creating their login happen in one visit.
  8. **Promote to roster** (accepted signups, plus existing players aging up from a predecessor
     team): an admin/coach action that creates the `Player` from `player_first_name`/
     `player_last_name`/`date_of_birth` (no re-entry) for new signups, copies each
     `TryoutSignupPosition` row straight into `PlayerPosition` (same canonical `Position` list --
     direct copy), links the parent's `User` + `ParentPlayerLink` (created during step 7's accept),
     and bulk-reassigns `Player.team` for existing players moving up from the predecessor team
     (checklist UI, default-checked, per the original season-roll-up idea). No separate "assign the
     team" step needed -- it was already chosen in step 1/3.

  Fees do **not** carry over on promotion -- they're normally paid months before the new season
  starts, so this workflow doesn't need to touch `Fee`/`Payment` at all. Whether a player's
  `PlayerPosition` rows carry over or reset on age-up promotion is still an open call.

  **Email sending is deliberately deferred and does NOT block building the rest of this** --
  `config/settings.py` has no `EMAIL_BACKEND`/SMTP configured yet, and this feature (plus
  `ParentInvite`'s claim flow) is what will eventually need it. Until that infra exists, step 6's
  "reveal" just displays each response link (e.g. a copy-link button) once `decisions_finalized` is
  set, and the admin sends it manually (text, personal email, phone call) -- same token/schema, no
  rework needed. Adding automated email later is purely additive: a "send" action that emails the
  already-existing link, on top of the manual flow rather than replacing it.

- **Splitting a division into multiple teams reactively, based on tryout turnout.** The design above
  assumes one team per division/season, decided *before* tryouts open (nothing stops creating two
  named teams for the same division up front, e.g. "11U White"/"11U Blue" -- that already works with
  no extra code, since the unique constraint is on `Team(name, season_year)`, not `(division,
  season_year)`). The harder version -- not knowing team count until you see how many kids sign up,
  and splitting an already-collected pool of signups across teams after the fact -- isn't supported
  by the design above, since each signup points at one specific pre-created team. Deferred rather
  than guessed at: if/when this is actually needed, signups would need to point at something broader
  than a single `Team` (a lightweight "division" or "tryout session" grouping) that gets split into
  one or more teams only after evaluation.
