# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Django 5.0 site for a youth baseball club ("Choice Select"). Most of the site map below is built:
the public pages, login, and the parent/coach/admin dashboards all exist as function-based views with
per-app templates. There are still **no tests**. New work is usually either a remaining site-map
page, a refinement of an existing flow, or one of the Future ideas at the bottom of this file.

Where the code lives: public views are split by app (`apps/teams/views.py`, `apps/schedule/views.py`,
`apps/tryouts/views.py`, plus `config/views.py` for home/location); **every logged-in dashboard page —
parent, coach, and admin — lives in `apps/accounts/views.py`** with templates under
`apps/accounts/templates/accounts/`, regardless of which model it edits (fees, events, posters…).
Shared htmx fragments are in `templates/partials/`.

There is no running log of changes besides git history (a `CHANGELOG.md` was started and then
retired) — so **when you add or change a feature, update this file in the same commit**, including
correcting any statement here it makes false.

The scaffold was originally hand-written rather than produced by `django-admin startproject` (the authoring
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

python manage.py seed_demo_data               # demo teams/coaches/parents/players/posters (local)
python manage.py seed_demo_data --force --password <one-off-random>   # against a DEBUG=False (prod) DB
python manage.py seed_demo_data --galleries-only [--force]            # backfill player galleries only
```

`seed_demo_data` refuses to run when `DEBUG=False` unless given `--force`. Always pass a random
`--password` with `--force`: the default password is in git. Seeded user emails go through a Gmail
alias so demo sends never reach real people. The command also seeds a rolling
`TryoutYearSettings.next_tryout_date` so the home-page banner shows up in the demo.

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

These settings behave as feature switches:

- `USE_R2` — `True` routes uploads (coach/player photos, gallery, posters) to Cloudflare R2 through
  django-storages' S3 backend; `False` writes to `./media` and is the local default. With R2 on,
  `AWS_S3_CUSTOM_DOMAIN` (the bucket's public URL) must also be set, or the generated file URLs point
  at the private S3 endpoint and images don't load.
- `SITE_BASIC_AUTH_ENABLED` (+ `SITE_BASIC_AUTH_USER`/`_PASSWORD`) — a temporary site-wide HTTP Basic
  Auth gate (`config/middleware.py:BasicAuthMiddleware`) for keeping the public out until launch. It
  sits in front of *everything*, including `/admin/` and the app's own login, and is independent of
  it. It is off by default. If it's enabled with blank credentials it fails closed and nobody can get
  in. If the deployed site suddenly returns 401 for everyone, check these variables first. It
  also covers the public token links in emails (`/try-outs/respond/…`, `/accounts/invite/…`), so
  while it's on, a family needs the gate credentials just to open those links.
- `EMAIL_BACKEND` — console locally, Resend on Railway; see the email notes under the try-out
  workflow below.
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

## Site map

Target page structure. What's still unbuilt is listed right after it.

**Public (no login):** Home (mission blurb + upcoming try-out banner within 30 days) · Try-Outs
(process info + signup form) · Schedule (filterable by team) · Teams index → Team detail (roster w/
positions, coaching staff w/ head/assistant labels, filtered schedule) · Coaches index (optional) ·
Location/Directions · Contact · Login / Invite claim

**Parent (logged in):** Dashboard — per-kid card (next event, fee balance) → click-through to a full
payment history page (date/method/amount table + running total) — not just inline totals · Invite
second parent · Schedule (pre-filtered to their team)

**Coach (logged in):** Dashboard with a **team switcher** if linked to multiple teams (shows role —
head/assistant — per team, though permissions don't differ by role) · Roster (view/edit, incl.
positions, bulk-move players to another team) · Practice Schedule (edit) · Tournament Schedule
(edit) · Try-Out Sign-Ups (all teams, all years visible; Status and Decision editable only for
their own teams' signups)

**Admin (logged in):** Dashboard · Try-Out Sign-Ups — list w/ year filter, status change as a
**dropdown with a confirmation dialog** before it commits (this is the HTMX flow — see
`TryoutStatusChange` in the model layer) → per-kid detail · Fees & Payments — create/edit, record
payments, outstanding-balance dashboard · Teams — create/edit, assign coaches · Schedule Management
· Users & Linking — role assignment, parent-player link management/history · Coach Bios · Site
Content

**Built:** Home (`/`), with the poster section, the try-out announcement marquee driven by
`TryoutYearSettings.next_tryout_date`, and a Contact section at the bottom (there is no separate
contact page). Also built: Try-Outs sign-up (`/try-outs/`), Schedule (`/schedule/`), Teams index/detail
(`/teams/`), Coaches index/detail (`/teams/coaches/`), Player detail (`/teams/players/<pk>/`), and
Location (`/location/`; the address has one source of truth in `config/views.py`). Accounts pages:
login (email-based) with a role-based redirect from `/accounts/dashboard/` and one nav link per role
the user holds. Parent dashboard, payment history, second-parent invite + claim, and player profile/
gallery editing. Coach dashboard with team switcher, roster, practices, tournaments, and try-outs.
Admin dashboard with try-outs list/detail, fees and payments, coach bios, schedule, and try-out posters.

**Not built as site pages — done through Django admin (`/admin/`) instead:** Teams create/edit and
coach assignment (the Team change page has a Publish/Unpublish button, `TeamAdmin.publish_view`,
that toggles `is_public`), Users & Linking (the User add form collects name + roles up front), and
Site Content.

Shared building blocks to reuse rather than duplicate: the `templates/base.html` shell (header/nav,
footer with contact email + Facebook link), `templates/partials/_form_field.html` (include per bound
field to get label/help/error markup consistently), `templates/partials/_event_item.html`,
`_fee_ledger.html`, and `static/css/main.css`, which implements the visual design direction above.
htmx is served locally from `static/js/htmx.min.js`, not a CDN.

**Try-out posters** (`apps.tryouts.TryoutPoster`) are also built: the home page's "Upcoming
Try-Outs" section (`config/views.py:home`) shows the active poster. Only one poster may be `is_active` at a time
(`TryoutPoster.clean`, so it applies in both the dashboard form and Django admin; the dashboard form also shows a
pop-up when a second active one is rejected), and the public sign-up form is closed unless one is active,
since the active poster stands for "the currently open try-out". Admin uploads/manages them at `/dashboard/admin/tryout-posters/`
(`admin_tryout_posters_list`/`_add`/`_edit`/`_delete` in `apps/accounts/views.py`) — manual image
upload only for now (`poster_type` is `initial` or `supplemental`, matching the two poster designs
the club already uses). Auto-generating a poster from a background photo + logo + time/location was
considered but deferred: it needs the actual source assets (the background/dust stock photo as its
own file, and the specific bold-italic display font used) to reproduce the existing design, not just
approximate it — revisit once those are available.

The two real club posters are also in `seed_demo_data` now (`_seed_tryout_posters`, images in
`apps/accounts/management/commands/seed_posters/`) — they were only ever uploaded once by hand through
the admin UI, and a later unrelated `flush` silently wiped them since nothing re-created them. Any
future manually-uploaded content (posters, player photos an admin adds outside the seed flow, etc.)
has the same risk: a `flush` for an unrelated reseed takes it out too unless it's also in the seed
command. Worth deliberately deciding, next time something gets uploaded through the app rather than
seeded, whether it should be added to `seed_demo_data` too.

**Player detail is built as one tiered page, not three separate ones** (`apps.teams.views.player_detail`,
at `/teams/players/<pk>/`, template `apps/teams/templates/teams/player_detail.html`). A single view
computes the requesting user's tier via `_player_viewer_info` and reveals sections accordingly: tier 1
(public — name, photo, jersey number, position, team, a free-text `description`) is shown to anyone only
if both `Player.is_public_profile` (default `False`, opt-in) and the player's team are public; tier 2 adds
date of birth and linked-parent contact info, for that player's coach or linked parent; tier 3 adds the fee/
payment ledger, full parent-link history, and a link back to the original try-out sign-up if the player was
promoted from one, for admin only. `photo`/`description`/`is_public_profile` are edited from a *separate*
parent-facing page (`accounts.parent_player_profile_edit`, linked from the parent dashboard and from the
detail page itself when `can_edit_profile` is true) — deliberately not by coaches, unlike the rest of the
roster fields (name/DOB/jersey/position), which stay on the existing `PlayerRosterForm`/coach-roster flow.
Entry points link in from the public team roster, the coach roster page, and the parent dashboard.

The bottom of that page has a **"More Pictures of <first name>!" gallery** (`accounts.PlayerGalleryPhoto`):
linked parents add/delete photos inline (`accounts.parent_player_gallery_add`/`_delete`) -- no admin or
coach editing from the site (Django admin can still remove one); anyone who can view the page sees it.
Uploads are re-encoded to JPEG, max 1600px, EXIF-rotated (`accounts.forms.downsize_image`), capped at
`GALLERY_MAX_PHOTOS` per player, to stay inside R2's free tier. `seed_demo_data` gives each seeded player
0-4 gallery photos from the same `seed_player_photos/` pool (`_seed_player_gallery`, once per player like
the profile photo); photos parents upload through the app are *not* seeded, so a `flush` wipes those. Players
that predate gallery seeding can be backfilled without a flush via `seed_demo_data --galleries-only`
(add `--force` on prod): it only adds photos to name-matched demo players with none, never resets
passwords, and is idempotent. This is per-player and parent-uploaded, which is why it sidesteps the consent
question blocking the team-wide gallery idea under Future ideas.

Seed data note: `seed_demo_data` randomly assigns each seeded player a photo from
`apps/accounts/management/commands/seed_player_photos/` (real photos, consented, downsized to ~20KB each
specifically to stay well inside Cloudflare R2's free tier even after repeated `--force` reseeds against
the deployed DB) plus a placeholder `description` and a random `is_public_profile`. This only ever runs
once per player (gated on `created`, mirroring how `date_of_birth`/`jersey_number` are seeded) — it won't
clobber a profile edited later through the app.

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

**accounts** — `AUTH_USER_MODEL = "accounts.User"`. **Login is by email, not username**
(`USERNAME_FIELD = "email"`; there is no `username` column), and emails are unique regardless of
letter case (`unique_lower_email` constraint), so store and look them up in a way that respects that.
Roles are deliberately many-to-many rather than a
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
holds bio/photo, kept separate from the auth record (`contact_email` defaults to the coach's login
email). `PlayerPosition` is the player↔position M2M. `Team(name, season_year)` is unique at the DB
level, and seasons display as "2026-2027" via `Team.season_label`, never as a bare year. Two flags
gate visibility:
- `Team.is_public` (default `True`) hides a pre-created next-season team from **every** public
  surface: teams index/detail, the coaches pages, the schedule, and public player profiles. A coach
  whose only teams are hidden still appears on the coaches pages, with their team shown as "TBA".
- `Team.accepting_tryouts` is separate from `is_public`, and it scopes the team dropdown on the
  sign-up form.

**tryouts** — public, no-login submissions. Every `TryoutSignup` has an explicit `team` FK chosen
by the parent on the form, and **its season is `signup.team.season_year`** (`season_label`). The old
cutoff-date heuristic (`compute_tryout_year`, `DEFAULT_TRYOUT_YEAR_CUTOFF_*`) is gone.
`TryoutYearSettings` now only holds `next_tryout_date` for the home-page banner. The sign-up form is
open only if a `TryoutPoster` is active **and** at least one team has `accepting_tryouts`. A signup
has two separate axes, each with its own audit trail. Every edit must write an audit row, not just
change the field:
- `status` (contact/attendance logistics) → `TryoutStatusChange`. The dropdown has an htmx
  `hx-confirm` dialog.
- `coach_decision` (`undecided` → `invite`/`not_selected`) → `TryoutDecisionChange`. It commits
  immediately, with no confirm dialog.

Both are editable from the admin *and* coach try-out pages. Permission goes through
`_can_manage_tryout_signup`: admins can edit any signup, coaches only signups for teams they're
assigned to. The full signup → decision → email → family response → roster pipeline is described in
"Try-out → roster workflow" below.

**schedule** — one `Event` model covers both practices and tournaments via `event_type`. Both are
managed through one shared set of views (`accounts.coach_events`/`_add`/`_edit`/`_delete`, URL
segment `practices|tournaments` → `EVENT_KINDS`): coaches for their own teams, admins for any team
(entry point `/dashboard/admin/schedule/`), same scoping as the roster. Recurring
practices are materialized as individual rows by bulk-create; there is no series/recurrence-rule
concept. `status` drives a cancellation banner on the public schedule.

**fees** — ledger-style. `Fee` is what's owed, `Payment` rows are manually recorded against it. There
is **no payment processing and no card data** — if online payment is ever added it goes through
Stripe/Square. `Fee.amount_paid`/`.balance`/`.status` are Python properties that iterate
`self.payments.all()`, so any list of fees needs `prefetch_related("payments")` to avoid N+1, and
these cannot be used in `filter()`/`order_by()`.

**Team-wide fees are fanned out at creation time.** Choosing a team in `admin_fee_add` creates one
**full-amount** fee (not split) for each player currently on that team. No `Fee` row with only a
`team` set is ever saved, so every other fee/payment view deals only in ordinary per-player fees.
Players added to the team later do *not* get the fee automatically. Payments are recorded inline via
htmx (`_fee_ledger.html`). The Django admin's Fee page has no Payment inline, on purpose, so
payments go through the dashboard.

## Permissions

There's no separate permission framework. Each view checks roles (`is_admin`/`is_coach`/`is_parent`)
and raises `PermissionDenied`, and team-scoped views load their team through a scoping helper in
`apps/accounts/views.py`:
- `_get_coach_team_or_404` returns only teams the user coaches (via `TeamCoach`).
- `_get_roster_team_or_404` does the same but gives admins any team. It's used by the roster,
  practices, and tournaments pages.
- `_can_manage_tryout_signup` works the same way for try-out Status/Decision edits.

The rules: a coach edits their own team's roster, practices, and tournaments. Tournaments were
originally view-only for coaches and changed by request. A coach never sees fees unless they also hold
the Admin role. One specific head coach (the league owner) holds both roles for exactly this reason —
don't special-case him in code, the many-to-many roles model already covers it. Follow this pattern
for new views rather than inventing a decorator layer.

## Known gaps to build

- **No tests at all.** `_can_manage_tryout_signup`, the roster scoping helpers, fee fan-out, and
  `promote_signup_to_roster` are the highest-value places to start.
- No GameChanger ICS sync. If a subscribable feed is confirmed, `Event` gains a `source` field
  (manual vs. synced) and the coach/admin edit UI narrows to an override layer for cancellations.
- Team management, user/role management, and parent-player link management exist only in Django
  admin, not as site pages (see Site map).

## Try-out → roster workflow (built)

This used to be an 8-step plan under Future ideas. It is now built end to end, as follows:

1. **Next season's teams are pre-created** by an admin in Django admin, with `is_public=False` and
   `accepting_tryouts=True`. Next season's head coach can be assigned via `TeamCoach` right away.
   The team is published (see the Publish/Unpublish button) once its roster is ready.
2. **The parent picks the team on the sign-up form**. This also settles borderline-age kids: the
   parent just picks.
3. **A coach or admin sets `coach_decision` per signup** (see the tryouts domain notes; a third
   `maybe` state was tried and dropped).
4. **Sending is per signup, not a team-wide batch reveal.** On the coach's Try-Out Sign-Ups page
   (`coach_tryouts`/`coach_tryout_send_email`), a "Send Acceptance/Rejection Email" button appears
   next to a signup as soon as its decision is set. The button creates a `TryoutResponseInvite`
   (UUID token, 14-day expiry, single response, same pattern as `ParentInvite`), sends it
   (`apps/tryouts/emails.py`), and stamps `TryoutSignup.decision_emailed_at`. The button then locks
   and shows a "Sent" badge, and unlocks again if the decision later changes. There's no
   `Team.decisions_finalized` gate. That field was added and later removed, and only the migrations
   still mention it.
5. **The family responds without logging in** at `/try-outs/respond/<token>/` (Accept/Decline →
   `TryoutSignup.family_response`). On accept, the same visit creates or confirms their login, and
   that account is stored as `signup.responded_by`.
6. **Promotion to the roster is automatic on accept**, via `apps.tryouts.roster.promote_signup_to_roster`,
   called from the respond view. It creates the `Player` from the signup (no re-entry) on
   `signup.team` and copies `TryoutSignupPosition` → `PlayerPosition` directly. It also creates the
   `ParentPlayerLink` to `responded_by`, *not* to whoever matches `parent_email`, since the family may
   have typed a different address. It sets `signup.promoted_player`. The admin "Promote to Roster"
   button (`admin_tryout_promote`) is only a fallback for signups with no date of birth, which
   `Player` requires but the form doesn't: add the DOB in Django admin, then click it.
7. **Existing players age up** via the roster page's bulk move (`coach_roster_bulk_move`), which moves
   the checked players to another team. `PlayerPosition` rows **carry over** automatically, because
   they belong to the player, not the team.

Fees do **not** carry over on promotion. They're normally paid months before the new season starts,
so this workflow never touches `Fee`/`Payment`.

**Email sending:** `config/settings.py`'s `EMAIL_BACKEND` defaults to the console backend locally.
Railway is configured for `anymail.backends.resend.EmailBackend` (django-anymail + Resend), not
SMTP. Railway blocks all outbound SMTP ports (25/465/587) at the network level, confirmed by testing
directly from inside the deployed container, so raw SMTP can never work there regardless of
credentials. `choiceselectleague.org` **is verified** in Resend, so the site can send to any
recipient, including the `haewon201+<name>@gmail.com` aliases `seed_demo_data` uses (Gmail delivers
`+` aliases to the base inbox). The Resend account belongs to haewon201@gmail.com, not
haewonito@gmail.com. If sends suddenly only reach haewon201@gmail.com and nobody else, the domain
has lost its verification: without a verified domain, Resend's free tier only delivers to the
account owner's own address. That is especially likely during the club-domain switch below.
Cloudflare Email Routing only handles *inbound* mail to `info@…` and has no effect on sending.
**Sending domain:** `choiceselectleague.org` was registered 2026-09-27 for Resend. **TODO: switch to
`choiceselectclub.org`** -- it's a club, not a league; "league" was a naming slip. When switching,
re-verify the new domain in Resend, update `DEFAULT_FROM_EMAIL` on Railway, and let the league domain
lapse (turn off its auto-renew). The site itself is also served at `choiceselectleague.org`/`www.`
(Railway custom domain + `ALLOWED_HOSTS`). `info@choiceselectleague.org` is the public contact
address (`config/context_processors.py:GENERAL_CONTACT_EMAIL`, shown in the footer and on the home
page) and the `DEFAULT_FROM_EMAIL` default, forwarded to Gmail via Cloudflare Email Routing. All of
these move to the club domain in the switch too.
`ParentInvite` also has optional emailing: `ParentInvite.invitee_email`/`emailed_at` let the primary
parent email the link from `parent_invite_player`. This is in addition to the copy/paste link, which
is always shown too.

## Future ideas (nice-to-have, not scheduled)

- **Splitting a division into multiple teams reactively, based on tryout turnout.** The try-out workflow
  assumes one team per division/season, decided *before* tryouts open (nothing stops creating two
  named teams for the same division up front, e.g. "11U White"/"11U Blue" -- that already works with
  no extra code, since the unique constraint is on `Team(name, season_year)`, not `(division,
  season_year)`). The harder version -- not knowing team count until you see how many kids sign up,
  and splitting an already-collected pool of signups across teams after the fact -- isn't supported
  by that workflow, since each signup points at one specific pre-created team. Deferred rather
  than guessed at: if/when this is actually needed, signups would need to point at something broader
  than a single `Team` (a lightweight "division" or "tryout session" grouping) that gets split into
  one or more teams only after evaluation.

- **Team photo gallery.** A section at the bottom of the team detail page where that team's coaches,
  linked parents, and admins (never the public) can view/upload team photos -- practices, games,
  tournaments, etc. Motivation: parents want a central place for this instead of scattered group
  texts/social posts. Explicitly not being built yet -- deliberately deferred, not just unprioritized
  -- because of one unresolved question: not every parent may be comfortable with their kid's photo
  being visible even in this narrower coach/parent-only context, and there's no consent mechanism
  figured out yet for that. Open questions for whoever picks this up:
  - Is consent per-parent (a blanket "my kid can appear in team photos" toggle, e.g. alongside
    `Player.is_public_profile`) or per-photo (tag which players are in it, only show/notify consenting
    families, maybe blur/exclude non-consenting kids)? Per-parent is far simpler to build; per-photo is
    what parents probably actually picture when they imagine this feature.
  - Who moderates uploads -- any parent on the team, or admin-approval-only before a photo becomes
    visible to the team?
  - Does declining consent block a parent from *uploading* photos that include other consenting kids,
    or only from their own kid *appearing* in others' uploads?
  No design decided here on purpose -- existing patterns worth reusing once it is: the
  `Player.is_public_profile` opt-in-by-default-off precedent from the player detail page, and the
  coach/parent/admin tiering already built for that same page (`apps.teams.views._player_viewer_info`)
  for scoping who can see the gallery at all.
