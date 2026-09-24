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

# Fun, not real -- see seed_photos/README (none of these are photos of the
# actual named coaches). Keyed by the local part of each coach's email with
# "." replaced by "_", e.g. ryan.rickard@example.com -> ryan_rickard.jpg.
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
]

# (first, last, email, roles, coach assignments as list of (team_name, TeamCoachRole))
COACHES = [
    (
        "Ryan",
        "Rickard",
        "ryan.rickard@example.com",
        [Role.ADMIN, Role.COACH],
        [
            ("Choice Select 10U", TeamCoachRole.ASSISTANT),
            ("Choice Select 12U", TeamCoachRole.HEAD),
        ],
    ),
    (
        "Travis",
        "Roth",
        "travis.roth@example.com",
        [Role.COACH],
        [("Choice Select 10U", TeamCoachRole.ASSISTANT)],
    ),
    (
        "Sean",
        "Morris",
        "sean.morris@example.com",
        [Role.COACH],
        [("Choice Select 12U", TeamCoachRole.ASSISTANT)],
    ),
    (
        "Tom",
        "Nguyen",
        "tom.nguyen@example.com",
        [Role.COACH],
        [
            ("Choice Select 10U", TeamCoachRole.HEAD),
            ("Choice Select 12U", TeamCoachRole.HEAD),
        ],
    ),
]

ADMIN_ONLY = ("Sandra", "Lee", "sandra.lee@example.com")

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
            self._seed_fees()
            self._seed_schedule()
            self._seed_tryouts()

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded."))
        self.stdout.write(f"All seeded users share the password: {self.password}")
        self.stdout.write(
            f"Admin+head coach (dual role): {self.coaches['ryan.rickard@example.com'].email}"
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
            self._seed_coach_photo(profile, email)

            for team_name, coach_role in assignments:
                TeamCoach.objects.get_or_create(
                    team=self.teams[team_name],
                    coach=user,
                    defaults={"role": coach_role},
                )

            coaches[email] = user
        return coaches

    def _seed_coach_photo(self, profile, email):
        if profile.photo:
            return
        filename = email.split("@")[0].replace(".", "_") + ".jpg"
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
        admin_user = self.coaches["ryan.rickard@example.com"]

        for i, ((first, last), player) in enumerate(self.players.items()):
            parent_first = next(name_cycle)
            email = f"{parent_first.lower()}.{last.lower()}@example.com"
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
                second_email = f"{second_first.lower()}.{last.lower()}@example.com"
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

    # -- fees -----------------------------------------------------------------

    def _seed_fees(self):
        admin_user = self.coaches["ryan.rickard@example.com"]
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
        admin_user = self.coaches["ryan.rickard@example.com"]
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
        admin_user = self.coaches["ryan.rickard@example.com"]
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
                    "parent_email": f"{parent_first.lower()}.{last.lower()}.tryout@example.com",
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
