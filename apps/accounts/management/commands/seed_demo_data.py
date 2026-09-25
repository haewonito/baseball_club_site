import datetime
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    ParentInvite,
    ParentPlayerLink,
    Player,
    Role,
    User,
    UserRole,
)
from apps.fees.models import Fee, Payment, PaymentMethod
from apps.schedule.models import Event, EventStatus, EventType
from apps.teams.models import CoachProfile, Position, Team, TeamCoach, TeamCoachRole
from apps.tryouts.models import TryoutSignup, TryoutStatus, TryoutStatusChange

DEMO_PASSWORD = "demopass123"


def _demo_email(local_part):
    """
    Every seeded email routes through Haewon's own Gmail alias instead of an
    unreachable @example.com, so --force-seeding a real deployment (see
    seed_demo_data --force) lands every demo email in one inbox via Gmail's
    "+" addressing -- e.g. "ryan.rickard" -> "haewon201+ryan.rickard@gmail.com".
    """
    return f"haewon201+{local_part}@gmail.com"


# The admin+head-coach account is looked up by email repeatedly below --
# named once here instead of repeating the literal string at each call site.
ADMIN_HEAD_COACH_EMAIL = _demo_email("ryan.rickard")

# Fun, not real -- see seed_photos/README (none of these are photos of the
# actual named coaches). Keyed by the coach's name, lowercased with a "_"
# separator, e.g. Ryan Rickard -> ryan_rickard.jpg.
SEED_PHOTOS_DIR = Path(__file__).resolve().parent / "seed_photos"

TEAMS = [
    {
        "name": "Choice Select 10U",
        "division": "10U",
        # 2027 -> displays as "2026-2027" (Team.season_label).
        "season_year": 2027,
        "birth_year": 2016,
    },
    {
        "name": "Choice Select 12U",
        "division": "12U",
        "season_year": 2027,
        "birth_year": 2014,
    },
    {
        "name": "Choice Select 11U",
        "division": "11U",
        "season_year": 2027,
        "birth_year": 2015,
    },
]

# (first, last, email, roles, coach assignments as list of (team_name, TeamCoachRole))
COACHES = [
    (
        "Ryan",
        "Rickard",
        ADMIN_HEAD_COACH_EMAIL,
        [Role.ADMIN, Role.COACH],
        [
            ("Choice Select 10U", TeamCoachRole.ASSISTANT),
            ("Choice Select 12U", TeamCoachRole.HEAD),
        ],
    ),
    (
        "Tom",
        "Nguyen",
        _demo_email("tom.nguyen"),
        [Role.COACH],
        [
            ("Choice Select 10U", TeamCoachRole.HEAD),
            ("Choice Select 12U", TeamCoachRole.HEAD),
        ],
    ),
    # Choice Select 11U's parent-coaches -- each also holds Role.PARENT and
    # is linked to their own kid on the roster (see ELEVEN_U_PARENT_LINKS
    # and _seed_eleven_u_families below). Everyone's an assistant except
    # Shawn, who's head coach.
    (
        "Travis",
        "Roth",
        _demo_email("travis.roth"),
        [Role.PARENT, Role.COACH],
        [("Choice Select 11U", TeamCoachRole.ASSISTANT)],
    ),
    (
        "Mo",
        "Sifuentes",
        _demo_email("mo.sifuentes"),
        [Role.PARENT, Role.COACH],
        [("Choice Select 11U", TeamCoachRole.ASSISTANT)],
    ),
    (
        "Sean",
        "Morris",
        _demo_email("sean.morris"),
        [Role.PARENT, Role.COACH],
        [("Choice Select 11U", TeamCoachRole.ASSISTANT)],
    ),
    (
        "Shawn",
        "Lewis",
        _demo_email("shawn.lewis"),
        [Role.PARENT, Role.COACH],
        [("Choice Select 11U", TeamCoachRole.HEAD)],
    ),
    (
        "Ryan",
        "Richard",
        _demo_email("ryan.richard"),
        [Role.PARENT, Role.COACH],
        [("Choice Select 11U", TeamCoachRole.ASSISTANT)],
    ),
]

ADMIN_ONLY = ("Sandra", "Lee", _demo_email("sandra.lee"))

# (first, last, jersey_number, positions) per team
PLAYERS_BY_TEAM = {
    "Choice Select 10U": [
        ("Ethan", "Brooks", 2, [Position.SHORTSTOP, Position.SECOND_BASE]),
        ("Liam", "Foster", 4, [Position.CATCHER]),
        ("Noah", "Ramirez", 7, [Position.RIGHT_PITCHER, Position.FIRST_BASE]),
        ("Mason", "Delgado", 9, [Position.CENTER_FIELD]),
        ("Lucas", "Hoffman", 11, [Position.LEFT_FIELD]),
        ("Owen", "Price", 14, [Position.THIRD_BASE]),
        ("Jack", "Sullivan", 16, [Position.RIGHT_FIELD, Position.SECOND_BASE]),
        ("Elijah", "Ward", 21, [Position.LEFT_PITCHER]),
    ],
    "Choice Select 12U": [
        ("Ava", "Bennett", 3, [Position.SHORTSTOP]),
        ("Sophia", "Coleman", 5, [Position.CATCHER, Position.FIRST_BASE]),
        ("Mia", "Ellison", 8, [Position.RIGHT_PITCHER]),
        ("Isabella", "Grant", 10, [Position.CENTER_FIELD, Position.LEFT_FIELD]),
        ("Charlotte", "Huang", 12, [Position.THIRD_BASE]),
        ("Amelia", "Ibarra", 15, [Position.SECOND_BASE]),
        ("Harper", "Jansen", 18, [Position.RIGHT_FIELD]),
        ("Evelyn", "Kowalski", 23, [Position.LEFT_PITCHER, Position.FIRST_BASE]),
    ],
    "Choice Select 11U": [
        # Pitcher handedness wasn't specified for this team -- defaulted to
        # right-handed (Position.RIGHT_PITCHER) throughout.
        ("Jack", "Roth", 24, [Position.SHORTSTOP, Position.CATCHER, Position.RIGHT_PITCHER]),
        ("Carson", "Helstein", 28, [Position.FIRST_BASE, Position.RIGHT_PITCHER]),
        ("Charlie", "Barror", 13, [Position.THIRD_BASE, Position.SHORTSTOP]),
        ("Elijah", "Sifuentes", 99, [Position.CATCHER, Position.RIGHT_PITCHER]),
        ("Everett", "Haggard", 5, [Position.RIGHT_PITCHER, Position.FIRST_BASE]),
        ("Kellen", "Lewis", 8, [Position.LEFT_FIELD, Position.SECOND_BASE]),
        (
            "Lucas",
            "Richard",
            4,
            [Position.RIGHT_FIELD, Position.CENTER_FIELD, Position.RIGHT_PITCHER],
        ),
        (
            "John",
            "Morris",
            66,
            [Position.RIGHT_PITCHER, Position.THIRD_BASE, Position.LEFT_FIELD],
        ),
    ],
}

PARENT_FIRST_NAMES = [
    "James",
    "Patricia",
    "Robert",
    "Jennifer",
    "Michael",
    "Linda",
    "William",
    "Elizabeth",
    "David",
    "Barbara",
    "Richard",
    "Susan",
    "Joseph",
    "Jessica",
    "Thomas",
    "Sarah",
]

# Choice Select 11U player -> (parent first name, parent email). Linked
# explicitly here rather than via the generic auto-generated-parent cycle
# in _seed_parents. Travis/Mo/Sean/Shawn/Ryan are also coaches for this team
# (see COACHES above); Katie is parent-only, so she isn't in self.coaches
# and _seed_eleven_u_families creates her user directly. Charlie Barror and
# Everett Haggard weren't given a named parent, so they still fall through
# to the generic auto-generated-parent cycle like every other player.
ELEVEN_U_PARENT_LINKS = {
    ("Jack", "Roth"): ("Travis", _demo_email("travis.roth")),
    ("Carson", "Helstein"): ("Katie", _demo_email("katie.helstein")),
    ("Elijah", "Sifuentes"): ("Mo", _demo_email("mo.sifuentes")),
    ("John", "Morris"): ("Sean", _demo_email("sean.morris")),
    ("Kellen", "Lewis"): ("Shawn", _demo_email("shawn.lewis")),
    ("Lucas", "Richard"): ("Ryan", _demo_email("ryan.richard")),
}

# (first, last, birth_year, positions, status, team_name)
TRYOUT_SIGNUPS = [
    ("Carter", "Mills", 2016, [Position.SHORTSTOP], TryoutStatus.NEW, "Choice Select 10U"),
    ("Grace", "Nolan", 2015, [Position.CATCHER], TryoutStatus.CONTACTED, "Choice Select 10U"),
    (
        "Henry",
        "Ortiz",
        2014,
        [Position.RIGHT_PITCHER, Position.FIRST_BASE],
        TryoutStatus.ATTENDED,
        "Choice Select 12U",
    ),
    ("Ella", "Pierce", 2016, [Position.CENTER_FIELD], TryoutStatus.NEW, "Choice Select 10U"),
    (
        "Sebastian",
        "Quinn",
        2014,
        [Position.THIRD_BASE],
        TryoutStatus.CONTACTED,
        "Choice Select 12U",
    ),
    (
        "Zoey",
        "Rhodes",
        2015,
        [Position.LEFT_FIELD, Position.SECOND_BASE],
        TryoutStatus.ATTENDED,
        "Choice Select 12U",
    ),
]


class Command(BaseCommand):
    help = "Seeds the local/dev database with demo data: teams, coaches, players, parents, fees, schedule, tryouts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running even when settings.DEBUG is False (e.g. against a deployed database).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help=(
                "Password to set on every seeded user. Defaults to a fixed dev password -- "
                "always pass a one-off random value here with --force, since the default is "
                "public (it's in this file, in git)."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "settings.DEBUG is False -- refusing to seed demo data (looks like a production "
                "database). Pass --force if you really mean to."
            )
        if options["force"] and not options["password"]:
            raise CommandError(
                "Refusing to seed a non-local database with the default password (it's public, "
                "committed to git). Pass --password '<random one-off value>'."
            )

        self.password = options["password"] or DEMO_PASSWORD

        with transaction.atomic():
            self.roles = self._seed_roles()
            self.teams = self._seed_teams()
            self.coaches = self._seed_coaches()
            self.admin = self._seed_admin_only()
            self.players = self._seed_players()
            self._seed_parents()
            self._seed_eleven_u_families()
            self._seed_fees()
            self._seed_schedule()
            self._seed_tryouts()

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded."))
        self.stdout.write(f"All seeded users share the password: {self.password}")
        self.stdout.write(
            f"Admin+head coach (dual role): {self.coaches[ADMIN_HEAD_COACH_EMAIL].email}"
        )
        self.stdout.write(f"Admin-only: {self.admin.email}")

    # -- accounts ---------------------------------------------------------

    def _seed_roles(self):
        roles = {}
        for role in Role.values:
            obj, _ = UserRole.objects.get_or_create(role=role)
            roles[role] = obj
        return roles

    def _seed_coaches(self):
        coaches = {}
        for first, last, email, role_list, assignments in COACHES:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={"first_name": first, "last_name": last, "is_active": True},
            )
            user.set_password(self.password)
            user.first_name, user.last_name = first, last
            user.save()
            user.roles.set([self.roles[r] for r in role_list])

            profile, _ = CoachProfile.objects.get_or_create(
                coach=user,
                defaults={
                    "bio_text": f"{first} has been coaching with the club for several seasons."
                },
            )
            self._seed_coach_photo(profile, first, last)

            for team_name, coach_role in assignments:
                TeamCoach.objects.get_or_create(
                    team=self.teams[team_name],
                    coach=user,
                    defaults={"role": coach_role},
                )

            coaches[email] = user
        return coaches

    def _seed_coach_photo(self, profile, first, last):
        if profile.photo:
            return
        filename = f"{first.lower()}_{last.lower()}.jpg"
        photo_path = SEED_PHOTOS_DIR / filename
        if not photo_path.exists():
            return
        # `flush` wipes the DB but not the media/ dir, so a same-named file
        # from an earlier seed run may still be on disk -- delete it first
        # so storage reuses the deterministic filename instead of appending
        # a random suffix to avoid clobbering what it thinks is a different
        # file.
        target = f"coach_photos/{filename}"
        if profile.photo.storage.exists(target):
            profile.photo.storage.delete(target)
        with open(photo_path, "rb") as f:
            profile.photo.save(filename, File(f), save=True)

    def _seed_admin_only(self):
        first, last, email = ADMIN_ONLY
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={"first_name": first, "last_name": last, "is_active": True},
        )
        user.set_password(self.password)
        user.first_name, user.last_name = first, last
        user.save()
        user.roles.set([self.roles[Role.ADMIN]])
        return user

    # -- teams --------------------------------------------------------------

    def _seed_teams(self):
        teams = {}
        for t in TEAMS:
            team, _ = Team.objects.get_or_create(
                name=t["name"],
                season_year=t["season_year"],
                # accepting_tryouts=True so the public sign-up form has real
                # options to test against locally; is_public stays at its
                # model default (True) -- these are the club's existing,
                # already-public teams, not a pre-created draft.
                defaults={"division": t["division"], "accepting_tryouts": True},
            )
            teams[t["name"]] = team
        return teams

    def _seed_players(self):
        players = {}
        for team_data in TEAMS:
            team_name = team_data["name"]
            birth_year = team_data["birth_year"]
            for first, last, jersey, positions in PLAYERS_BY_TEAM[team_name]:
                player, _ = Player.objects.get_or_create(
                    first_name=first,
                    last_name=last,
                    team=self.teams[team_name],
                    defaults={
                        "date_of_birth": datetime.date(birth_year, 4, 15),
                        "jersey_number": jersey,
                    },
                )
                for position in positions:
                    player.positions.get_or_create(position=position)
                players[(first, last)] = player
        return players

    def _seed_parents(self):
        name_cycle = iter(PARENT_FIRST_NAMES * 2)
        admin_user = self.coaches[ADMIN_HEAD_COACH_EMAIL]

        for i, ((first, last), player) in enumerate(self.players.items()):
            if (first, last) in ELEVEN_U_PARENT_LINKS:
                # Handled explicitly by _seed_eleven_u_families instead.
                continue
            parent_first = next(name_cycle)
            email = _demo_email(f"{parent_first.lower()}.{last.lower()}")
            parent, _ = User.objects.get_or_create(
                email=email, defaults={"first_name": parent_first, "last_name": last}
            )
            parent.set_password(self.password)
            parent.first_name, parent.last_name = parent_first, last
            parent.save()
            parent.roles.set([self.roles[Role.PARENT]])

            ParentPlayerLink.objects.get_or_create(
                parent=parent, player=player, defaults={"created_by": admin_user}
            )

            # First player of each team gets a second parent, one linked
            # and one still pending via invite -- exercises both flows.
            if i in (0, len(PLAYERS_BY_TEAM["Choice Select 10U"])):
                second_first = next(name_cycle)
                second_email = _demo_email(f"{second_first.lower()}.{last.lower()}")
                second_parent, _ = User.objects.get_or_create(
                    email=second_email,
                    defaults={"first_name": second_first, "last_name": last},
                )
                second_parent.set_password(self.password)
                second_parent.save()
                second_parent.roles.set([self.roles[Role.PARENT]])
                ParentPlayerLink.objects.get_or_create(
                    parent=second_parent, player=player, defaults={"created_by": parent}
                )

                ParentInvite.objects.get_or_create(
                    player=player,
                    created_by=parent,
                    claimed_at=None,
                    defaults={},
                )

    def _seed_eleven_u_families(self):
        admin_user = self.coaches[ADMIN_HEAD_COACH_EMAIL]
        for (p_first, p_last), (parent_first, email) in ELEVEN_U_PARENT_LINKS.items():
            player = self.players[(p_first, p_last)]
            parent = self.coaches.get(email)
            if parent is None:
                # Katie Helstein -- parent only, not a coach.
                parent, _ = User.objects.get_or_create(
                    email=email,
                    defaults={"first_name": parent_first, "last_name": p_last},
                )
                parent.set_password(self.password)
                parent.first_name, parent.last_name = parent_first, p_last
                parent.save()
                parent.roles.set([self.roles[Role.PARENT]])

            ParentPlayerLink.objects.get_or_create(
                parent=parent, player=player, defaults={"created_by": admin_user}
            )

    # -- fees -----------------------------------------------------------------

    def _seed_fees(self):
        admin_user = self.coaches[ADMIN_HEAD_COACH_EMAIL]
        for i, ((first, last), player) in enumerate(self.players.items()):
            fee, _ = Fee.objects.get_or_create(
                player=player,
                description="2026 season registration",
                defaults={
                    "amount_due": 350,
                    "due_date": datetime.date(2026, 3, 1),
                    "created_by": admin_user,
                },
            )
            if fee.payments.exists():
                continue

            outcome = i % 3
            if outcome == 0:
                Payment.objects.create(
                    fee=fee,
                    amount=350,
                    method=PaymentMethod.VENMO,
                    paid_at=datetime.date(2026, 2, 10),
                    recorded_by=admin_user,
                )
            elif outcome == 1:
                Payment.objects.create(
                    fee=fee,
                    amount=150,
                    method=PaymentMethod.CHECK,
                    paid_at=datetime.date(2026, 2, 15),
                    recorded_by=admin_user,
                    notes="First installment",
                )
            # outcome == 2: left unpaid/overdue on purpose

    # -- schedule ---------------------------------------------------------------

    def _seed_schedule(self):
        admin_user = self.coaches[ADMIN_HEAD_COACH_EMAIL]
        today = timezone.localdate()
        next_tuesday = today + datetime.timedelta(days=(1 - today.weekday()) % 7 or 7)

        for team in self.teams.values():
            for week in range(4):
                practice_date = next_tuesday + datetime.timedelta(weeks=week)
                start = timezone.make_aware(
                    datetime.datetime.combine(practice_date, datetime.time(18, 0))
                )
                end = start + datetime.timedelta(hours=1, minutes=30)
                Event.objects.get_or_create(
                    team=team,
                    event_type=EventType.PRACTICE,
                    start_datetime=start,
                    defaults={
                        "title": "Weekly practice",
                        "end_datetime": end,
                        "location_name": "Community Park Field 2",
                        "status": EventStatus.CANCELLED
                        if week == 2
                        else EventStatus.SCHEDULED,
                        "created_by": admin_user,
                    },
                )

            tournament_date = today + datetime.timedelta(days=30)
            start = timezone.make_aware(
                datetime.datetime.combine(tournament_date, datetime.time(9, 0))
            )
            Event.objects.get_or_create(
                team=team,
                event_type=EventType.TOURNAMENT,
                start_datetime=start,
                defaults={
                    "title": "Fall Classic",
                    "end_datetime": start + datetime.timedelta(hours=6),
                    "location_name": "Regional Sports Complex",
                    "location_address": "1200 Diamond Way",
                    "created_by": admin_user,
                },
            )

    # -- tryouts ------------------------------------------------------------------

    def _seed_tryouts(self):
        admin_user = self.coaches[ADMIN_HEAD_COACH_EMAIL]
        for i, (first, last, birth_year, positions, status, team_name) in enumerate(
            TRYOUT_SIGNUPS
        ):
            parent_first = PARENT_FIRST_NAMES[i]
            signup, created = TryoutSignup.objects.get_or_create(
                player_first_name=first,
                player_last_name=last,
                defaults={
                    "team": self.teams[team_name],
                    "date_of_birth": datetime.date(birth_year, 6, 1),
                    "years_experience": 2,
                    "parent_first_name": parent_first,
                    "parent_last_name": last,
                    "parent_phone": "555-0100",
                    "parent_email": _demo_email(f"{parent_first.lower()}.{last.lower()}.tryout"),
                    "status": status,
                },
            )
            if not created:
                continue

            for position in positions:
                signup.positions.get_or_create(position=position)

            if status != TryoutStatus.NEW:
                TryoutStatusChange.objects.create(
                    signup=signup,
                    old_status=TryoutStatus.NEW,
                    new_status=status,
                    changed_by=admin_user,
                )
